"""Lab bots, merged from the stand-alone lab_bot (2026-10) into the web app.

The bots run in the one process that owns the background jobs (``jobs.scheduler.start_background_jobs``):
listeners as daemon threads, the others as APScheduler jobs; with ``DEBUG=True`` none of them start.
Admin › Bots (``/admin/bots``) shows each bot's state, recent events and log from any gunicorn worker.

    gcn         GCN circulars and Einstein Probe WXT alerts (Kafka) → Slack, EP also by email   gcn.py
    astronote   new TNS AstroNotes → Slack, every 5 minutes                                      astronote.py
    obs_log     Lulin raw frames (FITS headers) → obs.logs "observed", daily 12:00 UTC+8         obs_log.py
    reduction   the Lulin reduction pipeline (auto_calibration.sh), step by step                 reduction.py
    detect      the embedded DETECT pipeline: cross-match, host rule, screening (every run, any trigger)   detect.py
    nas_backup  old raw nights, masters and calibrated targets of the reduction folder → lab NAS (SMB)   nas_backup.py

Each bot logs to the logger ``bot.<id>``: app/log/bots/<id>.log (rotating) and the daily web log.
State lives in ``status`` (app/log/.bot_status.json, shared by every worker).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Bot:
    id: str
    name: str
    kind: str                 # 'listener' (always on) or 'scheduled'
    schedule: str             # shown on the page
    about: str
    can_run: bool = False     # "Run now" button
    can_stop: bool = False    # "Stop" button while running
    stale_after: int = 0      # listener: seconds without a heartbeat before it counts as stalled
    links: tuple = field(default_factory=tuple)   # ((label, url), …)


BOTS = (
    Bot('gcn', 'GCN & Einstein Probe', 'listener', 'Always on · NASA GCN Kafka',
        'Posts new GCN circulars to Slack. Einstein Probe WXT alerts get an SLT script, a Lulin visibility plot, '
        'a Slack post and an email.', stale_after=180),
    Bot('astronote', 'TNS AstroNotes', 'scheduled', 'Every 5 min',
        'Posts new TNS AstroNotes to Slack.', can_run=True),
    Bot('obs_log', 'Observation log', 'scheduled', 'Daily 12:00 UTC+8 · last 15 nights',
        'Reads the FITS headers of the synced Lulin raw frames and marks each target as observed in the observation log.',
        can_run=True, links=(('Daily Trigger', '/daily_trigger'),)),
    Bot('reduction', 'Reduction pipeline', 'scheduled', 'Manual unless REDUCTION_HOUR_UTC is set',
        'Runs the Lulin reduction pipeline (auto_calibration.sh): sync raw frames, calibrate, plate solve.',
        can_run=True, can_stop=True, links=(('Pipeline', '/pipeline/reduction'),)),
    Bot('detect', 'DETECT', 'scheduled', 'TNS-DETECT · LSST-DETECT',
        'Cross-matches TNS objects and LSST alerts with galaxy and lens catalogues, applies the host rule and screens '
        'them for review.', can_run=True, links=(('TNS-DETECT', '/detect'), ('LSST-DETECT', '/detect/lsst'))),
    Bot('nas_backup', 'NAS backup', 'scheduled', 'Every 60 min once NAS_IP / NAS_PATH are set',
        'Moves what the reduction pipeline no longer needs to the lab NAS: raw nights older than last month, masters '
        'older than 30 days, calibrated targets without a new frame for 60 days.', can_run=True),
)
BY_ID = {b.id: b for b in BOTS}


def disabled():
    """Bot ids switched off with BOTS_DISABLED (comma separated), e.g. while the old lab_bot still runs."""
    import os
    return {x.strip() for x in (os.environ.get('BOTS_DISABLED') or '').split(',') if x.strip()}


def setup_problems():
    """What each bot is missing right now (settings, folders), so a page shows it before the first run."""
    from . import astronote, gcn, nas_backup, obs_log, reduction
    from . import detect as detect_bot
    raw = obs_log.raw_dir()
    out = {'gcn': gcn.setup_problem(), 'astronote': astronote.setup_problem(), 'reduction': reduction.setup_problem(),
           'detect': detect_bot.setup_problem(), 'nas_backup': nas_backup.setup_problem(),
           'obs_log': '' if raw and raw.is_dir() else f'Raw frame folder not found: {raw or "(not set)"} — set OBS_RAW_DIR or REDUCTION_PIPELINE_DIR.'}
    return {k: v for k, v in out.items() if v}
