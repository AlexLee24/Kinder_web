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
        from modules.postgres_database import search_tns_objects
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
        from modules.postgres_database import search_tns_objects, get_tns_db_connection
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
                "SELECT COUNT(*) FROM photometry WHERE object_name = %s", (name,)
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
