# Kinder Web

Flask web platform for the Kinder transient survey (NCU GREAT Lab): TNS marshal, object
pages with photometry/spectroscopy, DETECT host screening, observation planning tools,
Daily Trigger to Slack, and a small public REST API.

## Quick start

```bash
uv sync                               # Python 3.12, deps from pyproject.toml / uv.lock
uv run playwright install chromium    # only needed for the photometry fetcher
cp kinder.env.example kinder.env      # then fill in the values
git clone https://github.com/AlexLee24/CASTOR.git app/vendor/CASTOR   # exposure-time engine
uv run python main.py                 # dev server (or run.py); logs go to the terminal AND app/log/
```

Production (behind an HTTPS proxy), from the project root:

```bash
gunicorn --workers 4 --worker-class gthread --threads 4 --bind 127.0.0.1:8000 wsgi:app
```

Both entry points start immediately (the start-up backup runs in a background thread) and
write every log line to the terminal as well as `app/log/<date>.log`.
`cd app && gunicorn main:app` still works through the `app/main.py` shim.

## Where things are

```
main.py / run.py / wsgi.py  entry points (dev server / gunicorn) -> app.create_app()
kinder.env                  settings & secrets (see kinder.env.example)
app/
  __init__.py               create_app(): the application factory
  config.py                 Config object (reads kinder.env)
  paths.py                  every on-disk location; puts vendored packages on sys.path
  extensions.py             OAuth client
  core/                     request hooks, auth helpers/decorators, static-file route,
                            logging, URL converters, template filters, param validation
  db/                       PostgreSQL access layer: auth.py / transient.py / obs.py / catalog.py
  services/                 domain logic, one package per topic:
    tns/                    hourly/daily TNS sync, manual download, kinder_id gap filler
    photometry/             light-curve fetcher (download_phot.py, private), scheduler, plotting
    detect/                 wrappers around the vendored DETECT pipeline
    planning/               visibility plots, ACP scripts, Daily Trigger Slack send
    astro/                  calculators & converters (distance, extinction, coords, dates, ...)
    jobs/                   background scheduler, backup, DB monitor, job status
    notifications/          email, GCN alerts
  blueprints/               one folder per site area = routes + templates + static
    basic/  auth/  marshal/  detect/  astronomy_tools/  planners/  private_area/  web_api/  games/
  resources/                small data files kept in git (KN model, filter colours)
  vendor/                   CASTOR (git clone, ignored) and DETECT (rsync copy, tracked)
  data/  log/               runtime data and daily logs (git-ignored)
docs/
  FEATURES.md               complete feature & navigation reference (per-route, per-page)
  ARCHITECTURE.md           layout, conventions, how to add a page, old->new path map
  database/                 schema notes and DDL for the Kinder PostgreSQL database
tests/                      pytest (needs the live database): python -m pytest -q
scripts/sync_detect.sh      refresh app/vendor/DETECT from a DETECT checkout
```

To find a page: start from the navbar entry in `docs/FEATURES.md` §2, which names the
blueprint; the blueprint folder under `app/blueprints/` holds its routes (`routes.py` or
topic modules), `templates/` and `static/`.

## Tests

```bash
.venv/bin/python -m pytest -q                 # all (structural + live-DB page checks)
.venv/bin/python -m pytest -q -m "not live_db"
.venv/bin/python tests/tools/smoke_pages.py tests/smoke_after.json   # GET every route as 4 personas
```
