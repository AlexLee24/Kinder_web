"""Admin panel actions — scheduled_jobs (split from admin_routes.py)."""
from flask import jsonify
from datetime import datetime
from . import admin_bp
from .helpers import _SCHEDULED_JOBS
from app.core.auth import admin_required


def _calc_next_run(trigger_type, **kwargs):
    """Compute the next fire time from a trigger definition (pure Python, no APScheduler needed).
    Used as fallback when the scheduler lives in another gunicorn worker."""
    from datetime import timezone, timedelta
    now = datetime.now(timezone.utc)
    try:
        if trigger_type == 'cron':
            hour = kwargs.get('hour', 0)
            minute = kwargs.get('minute', 0)
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate.isoformat()
        elif trigger_type == 'interval':
            return (now + timedelta(minutes=kwargs['minutes'])).isoformat()
    except Exception:
        pass
    return None

@admin_bp.route('/admin/scheduled-jobs-status')
@admin_required
def scheduled_jobs_status():

    from app.services.jobs import scheduler_state as _sched_state
    from app.services.jobs import job_status as _js

    sched = _sched_state.scheduler
    all_records = _js.get_all()

    jobs_out = []
    for job_id, (label, schedule_desc, trigger_type, trigger_kwargs) in _SCHEDULED_JOBS.items():
        rec = all_records.get(job_id, {})

        # Prefer live APScheduler value (works when this worker owns the scheduler)
        next_run = None
        if sched:
            job = sched.get_job(job_id)
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()
        # Fallback: compute from trigger definition (other workers, DEBUG mode)
        if not next_run:
            next_run = _calc_next_run(trigger_type, **trigger_kwargs)

        jobs_out.append({
            'id': job_id,
            'name': label,
            'schedule': schedule_desc,
            'next_run': next_run,
            'is_running': _js.is_running(job_id),
            'last_status': rec.get('status'),
            'last_message': rec.get('message', ''),
            'last_run_at': rec.get('finished_at'),
        })

    return jsonify({'jobs': jobs_out})
