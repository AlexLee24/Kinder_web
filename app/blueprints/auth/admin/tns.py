"""Admin panel actions — tns (split from admin_routes.py)."""
from flask import request, jsonify
from datetime import datetime
import logging
from app.core.auth import admin_required

logger = logging.getLogger(__name__)
from . import admin_bp
from .helpers import _tns_task_status


@admin_bp.route('/admin/tns-download-hourly', methods=['POST'])
@admin_required
def tns_download_hourly():
    if _tns_task_status['running']:
        return jsonify({'success': False, 'message': 'A TNS task is already running'}), 409

    import threading
    from datetime import timezone

    def _run():
        _tns_task_status['running'] = True
        _tns_task_status['message'] = 'Running...'
        try:
            from app.services.tns.auto_tns_download import download_TNS_api_hr, addin_database, auto_snoozed, SAVE_DIR, _run_detect_after_import
            hr = f"{datetime.now(timezone.utc).hour:02d}"
            logger.info('[TNS Manual] hourly task started by admin, hr=%s', hr)
            if download_TNS_api_hr(hr):
                work_csv = SAVE_DIR / 'tns_public_objects_WORK.csv'
                logger.info('[TNS Manual] hourly download ok, importing CSV: %s', work_csv)
                if addin_database(str(work_csv)):
                    _tns_task_status['message'] = 'Import done, running DETECT...'
                    _run_detect_after_import(new_only=False, label='TNS-hourly (manual)')
                logger.info('[TNS Manual] hourly import done, running auto_snoozed')
                auto_snoozed(datetime.now(timezone.utc))
                _tns_task_status['message'] = f'Hourly download (hr={hr}) + import + DETECT + snooze done.'
                logger.info('[TNS Manual] hourly task completed, hr=%s', hr)
            else:
                _tns_task_status['message'] = f'Download failed for hr={hr}.'
                logger.warning('[TNS Manual] hourly download failed, hr=%s', hr)
        except Exception as e:
            logger.exception('TNS hourly task error: %s', e)
            _tns_task_status['message'] = f'Error: {e}'
        finally:
            _tns_task_status['running'] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'success': True, 'message': 'TNS hourly download started in background'})

@admin_bp.route('/admin/tns-download-daily', methods=['POST'])
@admin_required
def tns_download_daily():
    if _tns_task_status['running']:
        return jsonify({'success': False, 'message': 'A TNS task is already running'}), 409

    import threading
    from datetime import timezone, timedelta

    data = request.get_json(silent=True) or {}
    date_str = data.get('date', '')  # optional YYYY-MM-DD override

    def _run():
        _tns_task_status['running'] = True
        _tns_task_status['message'] = 'Running...'
        try:
            from app.services.tns.auto_tns_download import download_TNS_api, addin_database, auto_snoozed, SAVE_DIR, _run_detect_after_import
            if date_str:
                try:
                    dt = datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError:
                    _tns_task_status['message'] = 'Invalid date format'
                    logger.warning('[TNS Manual] daily task invalid date format: %s', date_str)
                    return
            else:
                dt = datetime.now(timezone.utc) - timedelta(days=1)
            logger.info('[TNS Manual] daily task started by admin, date=%s', dt.date())
            if download_TNS_api(dt.year, dt.month, dt.day):
                work_csv = SAVE_DIR / 'tns_public_objects_WORK.csv'
                logger.info('[TNS Manual] daily download ok, importing CSV: %s', work_csv)
                if addin_database(str(work_csv)):
                    _tns_task_status['message'] = 'Import done, running DETECT on new objects...'
                    _run_detect_after_import(new_only=True, label='TNS-daily (manual)')
                logger.info('[TNS Manual] daily import done, running auto_snoozed')
                auto_snoozed(datetime.now(timezone.utc))
                _tns_task_status['message'] = f'Daily download ({dt.date()}) + import + DETECT + snooze done.'
                logger.info('[TNS Manual] daily task completed, date=%s', dt.date())
            else:
                _tns_task_status['message'] = f'Download failed for {dt.date()}.'
                logger.warning('[TNS Manual] daily download failed, date=%s', dt.date())
        except Exception as e:
            logger.exception('TNS daily task error: %s', e)
            _tns_task_status['message'] = f'Error: {e}'
        finally:
            _tns_task_status['running'] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'success': True, 'message': 'TNS daily download started in background'})

@admin_bp.route('/admin/tns-auto-snooze', methods=['POST'])
@admin_required
def tns_auto_snooze():
    if _tns_task_status['running']:
        return jsonify({'success': False, 'message': 'A TNS task is already running'}), 409

    import threading
    from datetime import timezone

    def _run():
        _tns_task_status['running'] = True
        _tns_task_status['message'] = 'Running...'
        try:
            from app.services.tns.auto_tns_download import auto_snoozed
            logger.info('[TNS Manual] auto-snooze started by admin')
            auto_snoozed(datetime.now(timezone.utc))
            _tns_task_status['message'] = 'Auto-snooze completed.'
            logger.info('[TNS Manual] auto-snooze completed')
        except Exception as e:
            logger.exception('TNS auto-snooze error: %s', e)
            _tns_task_status['message'] = f'Error: {e}'
        finally:
            _tns_task_status['running'] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'success': True, 'message': 'Auto-snooze started in background'})

@admin_bp.route('/admin/tns-task-status')
@admin_required
def tns_task_status():
    return jsonify(_tns_task_status)
