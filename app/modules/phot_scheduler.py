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


def get_progress():
    return dict(_progress)
