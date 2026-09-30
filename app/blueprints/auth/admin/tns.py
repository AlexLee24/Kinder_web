"""Admin panel actions — tns (split from admin_routes.py)."""
from flask import request, jsonify
from datetime import datetime
import logging
from app.core.auth import admin_required

logger = logging.getLogger(__name__)
from . import admin_bp
from .helpers import _tns_task_status, _claim_task, _start_claimed_task


@admin_bp.route('/admin/tns-download-hourly', methods=['POST'])
@admin_required
def tns_download_hourly():
    if _tns_task_status['running']:
        return jsonify({'success': False, 'message': 'A TNS task is already running'}), 409

    from datetime import timezone

    def _run():
        work_csv = None
        try:
            from app.services.tns.auto_tns_download import download_TNS_api_hr, addin_database, auto_snoozed, new_work_csv_path, _run_detect_after_import
            hr = f"{datetime.now(timezone.utc).hour:02d}"
            logger.info('[TNS Manual] hourly task started by admin, hr=%s', hr)
            work_csv = new_work_csv_path(f'manual_hr{hr}')
            csv_path = download_TNS_api_hr(hr, dest=work_csv)
            if csv_path:
                logger.info('[TNS Manual] hourly download ok, importing CSV: %s', csv_path)
                if addin_database(str(csv_path)):
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
            if work_csv is not None:
                try:
                    work_csv.unlink(missing_ok=True)
                except OSError:
                    pass
            _tns_task_status['running'] = False

    if not _claim_task(_tns_task_status):
        return jsonify({'success': False, 'message': 'A TNS task is already running'}), 409
    _start_claimed_task(_tns_task_status, _run)
    return jsonify({'success': True, 'message': 'TNS hourly download started in background'})

@admin_bp.route('/admin/tns-download-daily', methods=['POST'])
@admin_required
def tns_download_daily():
    if _tns_task_status['running']:
        return jsonify({'success': False, 'message': 'A TNS task is already running'}), 409

    from datetime import timezone, timedelta

    data = request.get_json(silent=True) or {}
    date_str = data.get('date', '')  # optional YYYY-MM-DD override

    def _run():
        work_csv = None
        try:
            from app.services.tns.auto_tns_download import download_TNS_api, addin_database, auto_snoozed, new_work_csv_path, _run_detect_after_import
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
            work_csv = new_work_csv_path(f'manual_{dt:%Y%m%d}')
            csv_path = download_TNS_api(dt.year, dt.month, dt.day, dest=work_csv)
            if csv_path:
                logger.info('[TNS Manual] daily download ok, importing CSV: %s', csv_path)
                if addin_database(str(csv_path)):
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
            if work_csv is not None:
                try:
                    work_csv.unlink(missing_ok=True)
                except OSError:
                    pass
            _tns_task_status['running'] = False

    if not _claim_task(_tns_task_status):
        return jsonify({'success': False, 'message': 'A TNS task is already running'}), 409
    _start_claimed_task(_tns_task_status, _run)
    return jsonify({'success': True, 'message': 'TNS daily download started in background'})

@admin_bp.route('/admin/tns-auto-snooze', methods=['POST'])
@admin_required
def tns_auto_snooze():
    if _tns_task_status['running']:
        return jsonify({'success': False, 'message': 'A TNS task is already running'}), 409

    from datetime import timezone

    def _run():
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

    if not _claim_task(_tns_task_status):
        return jsonify({'success': False, 'message': 'A TNS task is already running'}), 409
    _start_claimed_task(_tns_task_status, _run)
    return jsonify({'success': True, 'message': 'Auto-snooze started in background'})

@admin_bp.route('/admin/tns-task-status')
@admin_required
def tns_task_status():
    return jsonify(_tns_task_status)
