"""Domain logic that is independent of Flask request handling.

    tns/            TNS download / import / gap filling (the hourly & daily sync)
    photometry/     light-curve fetching (ATLAS, Pan-STARRS, ZTF, LSST), scheduling, plotting
    detect/         wrappers around the vendored DETECT pipeline
    planning/       observation planning, ACP script generation, Daily Trigger Slack send
    astro/          calculators & converters (distance, extinction, coordinates, dates, filter colours, spectral lines)
    jobs/           background scheduler, backup, DB monitor, job status registry
    notifications/  email and GCN alerts

Routes in ``app.blueprints`` call into these modules; these modules must not import
from ``app.blueprints`` (the one exception, the DETECT page cache warm-up in
``jobs/scheduler.py``, is documented there).
"""
