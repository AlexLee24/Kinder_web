"""
Scheduled photometry fetch for all Inbox objects.
Runs daily at UTC+8 09:00 (UTC 01:00).
"""
import threading
import logging

logger = logging.getLogger(__name__)

# Prevent concurrent runs
_running = False
_lock = threading.Lock()
_progress = {"current": 0, "total": 0, "success": 0, "failed": 0}


def fetch_inbox_photometry():
    """Fetch photometry for every Inbox (tag='object') object."""
    global _running, _progress

    with _lock:
        if _running:
            logger.warning("fetch_inbox_photometry is already running, skipping.")
            return {"skipped": True, "reason": "Already running"}
        _running = True
        _progress = {"current": 0, "total": 0, "success": 0, "failed": 0}

    success_count = 0
    fail_count = 0
    failed_objects = []

    try:
        from modules.database.transient import search_tns_objects
        from modules.download_phot import process_single_object_workflow

        objects = search_tns_objects(tag='object', limit=9999, sort_by='name', sort_order='asc')
        logger.info(f"fetch_inbox_photometry: found {len(objects)} inbox objects")
        _progress["total"] = len(objects)

        for i, obj in enumerate(objects, 1):
            name = obj.get('name', '').strip()
            if not name:
                continue
            if (obj.get('name_prefix') or '').strip().upper() == 'FRB':
                _progress["current"] = i
                continue
            _progress["current"] = i
            try:
                logger.info(f"============ {i}/{len(objects)} {name}: fetching photometry ============")
                process_single_object_workflow(name)
                success_count += 1
                _progress["success"] = success_count
            except Exception as e:
                logger.error(f"Failed to fetch photometry for {name}: {e}")
                fail_count += 1
                failed_objects.append(name)
                _progress["failed"] = fail_count

        logger.info(
            f"fetch_inbox_photometry done: {success_count} succeeded, {fail_count} failed"
        )
        return {
            "skipped": False,
            "total": len(objects),
            "success": success_count,
            "failed": fail_count,
            "failed_objects": failed_objects,
        }

    except Exception as e:
        logger.error(f"fetch_inbox_photometry error: {e}")
        return {"skipped": False, "total": 0, "success": 0, "failed": 0, "error": str(e)}

    finally:
        with _lock:
            _running = False


def is_running():
    return _running


_running_missing = False
_lock_missing = threading.Lock()


def is_missing_running():
    return _running_missing


def fetch_missing_photometry():
    """Hourly job: fetch photometry only for inbox objects that have zero data points."""
    global _running_missing

    with _lock_missing:
        if _running_missing:
            logger.warning("fetch_missing_photometry already running, skipping.")
            return {"skipped": True, "reason": "Already running"}
        # Also skip if daily full-fetch is active
        if _running:
            logger.info("fetch_missing_photometry: daily fetch in progress, skipping.")
            return {"skipped": True, "reason": "Daily fetch running"}
        _running_missing = True

    success_count = 0
    fail_count = 0
    checked = 0
    triggered = 0

    try:
        from modules.database.transient import search_tns_objects
        from modules.database import get_tns_db_connection
        from modules.download_phot import process_single_object_workflow

        objects = search_tns_objects(tag='object', limit=9999, sort_by='name', sort_order='asc')
        logger.info(f"fetch_missing_photometry: checking {len(objects)} inbox objects")

        conn = get_tns_db_connection()
        cursor = conn.cursor()

        for obj in objects:
            name = obj.get('name', '').strip()
            if not name:
                continue
            if (obj.get('name_prefix') or '').strip().upper() == 'FRB':
                continue
            checked += 1
            cursor.execute(
                "SELECT COUNT(*) FROM transient.photometry p "
                "JOIN transient.objects o ON p.obj_id=o.obj_id "
                "WHERE o.name = %s", (name,)
            )
            count = cursor.fetchone()[0]
            if count > 0:
                continue

            triggered += 1
            try:
                logger.info(f"fetch_missing_photometry: {name} has no phot, fetching...")
                process_single_object_workflow(name)
                success_count += 1
            except Exception as e:
                logger.error(f"fetch_missing_photometry: failed for {name}: {e}")
                fail_count += 1

        cursor.close()
        conn.close()

        logger.info(
            f"fetch_missing_photometry done: checked={checked}, triggered={triggered}, "
            f"success={success_count}, failed={fail_count}"
        )
        return {
            "skipped": False,
            "checked": checked,
            "triggered": triggered,
            "success": success_count,
            "failed": fail_count,
        }

    except Exception as e:
        logger.error(f"fetch_missing_photometry error: {e}")
        return {"skipped": False, "error": str(e)}

    finally:
        with _lock_missing:
            _running_missing = False


def get_progress():
    return dict(_progress)


def update_target_mags():
    """Daily job at 05:00: for each active observation target, find the latest
    non-upper-limit magnitude from the TNS photometry table and update mag field.
    Also syncs prefix (AT→SN) in observation_targets and observation_logs.
    EP-prefixed names are resolved via tns_objects internal_names/tags."""
    try:
        from modules.database import get_db_connection, get_tns_db_connection
        from modules.database.obs import get_observation_targets

        targets = get_observation_targets()
        active = [t for t in targets if t.get('is_active') and t.get('name', '').strip()]
        if not active:
            logger.info("update_target_mags: no active targets, skipping.")
            return

        logger.info(f"update_target_mags: updating mag for {len(active)} active targets")

        tns_conn = get_tns_db_connection()
        tns_cursor = tns_conn.cursor()

        updated = 0
        log_synced = 0
        for t in active:
            full_name = t['name'].strip()
            bare_name = None
            current_prefix = ''

            is_ep = full_name.upper().startswith('EP')

            # --- EP name: look up via internal_names / tags, keep EP name as-is ---
            if is_ep:
                tns_cursor.execute(
                    """SELECT name FROM transient.objects
                       WHERE internal_name ILIKE %s
                          OR EXISTS (SELECT 1 FROM unnest(tag) t(v) WHERE t.v ILIKE %s)
                       LIMIT 1""",
                    (f'%{full_name}%', f'%{full_name}%')
                )
                ep_row = tns_cursor.fetchone()
                if ep_row is None:
                    logger.debug(f"update_target_mags: EP name {full_name} not found in tns_objects, skipping")
                    continue
                bare_name = ep_row[0].strip()
                # EP names are never renamed — keep full_name as new_full_name
                new_full_name = full_name
                name_changed = False
                logger.debug(f"update_target_mags: EP name {full_name} resolved bare_name={bare_name}")

            # --- Normal resolution: match full name or bare name ---
            else:
                tns_cursor.execute(
                    """SELECT name_prefix, name FROM transient.objects
                       WHERE (COALESCE(name_prefix,'') || name) = %s
                          OR name = %s
                       LIMIT 1""",
                    (full_name, full_name)
                )
                row = tns_cursor.fetchone()
                if row is None:
                    logger.debug(f"update_target_mags: {full_name} not found in tns_objects, skipping")
                    continue
                current_prefix = (row[0] or '').strip()
                bare_name = row[1].strip()
                new_full_name = current_prefix + bare_name
                name_changed = (new_full_name != full_name)

            # Latest non-upper-limit magnitude from photometry
            tns_cursor.execute(
                                """SELECT p.mag FROM transient.photometry p
                   JOIN transient.objects o ON p.obj_id=o.obj_id
                   WHERE o.name = %s
                                         AND p.mag IS NOT NULL
                                         AND CAST(p.mag AS TEXT) NOT LIKE '>%%'
                   ORDER BY p."MJD" DESC
                   LIMIT 1""",
                (bare_name,)
            )
            phot_row = tns_cursor.fetchone()
            new_mag = None
            if phot_row is not None:
                try:
                    new_mag = round(float(phot_row[0]), 2)
                except (TypeError, ValueError):
                    pass

            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Update observation_targets
                if new_mag is not None and name_changed:
                    cursor.execute(
                        "UPDATE obs.observation_targets SET mag = %s, name = %s WHERE id = %s",
                        (new_mag, new_full_name, t['id'])
                    )
                    updated += 1
                elif new_mag is not None:
                    cursor.execute(
                        "UPDATE obs.observation_targets SET mag = %s WHERE id = %s",
                        (new_mag, t['id'])
                    )
                    updated += 1
                elif name_changed:
                    cursor.execute(
                        "UPDATE obs.observation_targets SET name = %s WHERE id = %s",
                        (new_full_name, t['id'])
                    )
                    updated += 1

                if name_changed:
                    logger.info(f"update_target_mags: renamed {full_name} → {new_full_name} in targets")

                # Sync observation_logs for non-EP targets only
                # (EP names stay unchanged; sync AT<bare>/SN<bare>/bare → correct full_name)
                if not is_ep:
                    cursor.execute(
                        """UPDATE obs.observation_logs
                           SET target_name = %s
                           WHERE target_name != %s
                             AND (
                                 target_name = ('AT' || %s)
                                 OR target_name = ('SN' || %s)
                                 OR target_name = %s
                                 OR target_name = %s
                             )""",
                        (new_full_name, new_full_name,
                         bare_name, bare_name, bare_name, full_name)
                    )
                    n = cursor.rowcount
                    if n > 0:
                        log_synced += n
                        logger.info(f"update_target_mags: synced {n} log rows → {new_full_name}")

                conn.commit()
                cursor.close()

        tns_cursor.close()
        tns_conn.close()
        logger.info(
            f"update_target_mags done: {updated}/{len(active)} targets updated, "
            f"{log_synced} log rows synced"
        )
        return {"updated": updated, "total": len(active), "log_synced": log_synced}

    except Exception as e:
        logger.error(f"update_target_mags error: {e}")
        return {"error": str(e)}
