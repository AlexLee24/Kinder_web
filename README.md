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

### Required settings (kinder.env)

- `SECRET_KEY` must be set to a long random value; the app refuses to start without it
  (tests use a throwaway key automatically).
- The kinder.env local admin login is disabled unless `ADMIN_USERNAME`, `ADMIN_PASSWORD`
  **and** `ADMIN_LOCAL_EMAIL` are all set, and that email has a row in `auth.users`. It is a
  break-glass fallback of the login page's "Direct login" (used only when no DB account has
  that username); **leave it disabled in production unless you need it**.
- Scheduled jobs run in **UTC**.
- `MAX_CONTENT_LENGTH_MB` (default 64) caps request bodies.
- Rate limits are shared by all gunicorn workers on the host through a small SQLite file
  (`app/data/rate_limit.sqlite3`, override with `RATE_LIMIT_DB`).
- With `open_registration` off (admin panel), new Google accounts need a pending invitation.
- Admins create "direct login" accounts (Admin → Users → Add User): **username + password**,
  email optional (without one a placeholder `<username>@users.invalid` is stored as the internal
  identity key and hidden in the UI). Google-only accounts are added with just an email. There
  is no self sign-up for direct-login accounts. Users sign in on `/login` with their username
  (or email) and can change their password from their profile. Passwords are scrypt-hashed in
  `auth.users.password_hash` (columns added automatically at start-up).

## Security

- **Headers** (every response, `app/core/hooks.py`): enforced Content-Security-Policy
  (violations are reported to `POST /csp-report` and logged at WARNING),
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`,
  `Referrer-Policy: strict-origin-when-cross-origin`, a restrictive `Permissions-Policy`,
  COOP/CORP `same-origin`, HSTS (1 year, subdomains) on HTTPS when `DEBUG` is off, and
  `Cache-Control: no-store` for logged-in users, `/admin*` and `/api/*`. A view that sets its
  own CSP, CORP or Cache-Control keeps it.
- **Sessions**: signed cookie, `HttpOnly`, `SameSite=Lax`, `Secure` (env
  `SESSION_COOKIE_SECURE`, default on unless `DEBUG`). Idle timeout 8 h (1 h for admins),
  absolute lifetime 30 days; the session is rebuilt at every login. Password changes,
  "Log out all devices" (profile) and the admin's "Log out everywhere" end all other sessions.
  When the database is unreachable, admin-only actions answer 503 instead of trusting the cookie.
- **Google sign-in** requires a verified email and binds the Google account id (`sub`) to the
  user on first login; a different Google account for the same email is refused.
- **API keys** are stored only as a SHA-256 hash plus the last 4 characters. A key is shown
  exactly once when an admin issues it (or the user regenerates it on the profile page) and
  never appears in cookies, pages or logs (`api_key=` / `X-API-Key` values are redacted from
  every log line). Send it in the `X-API-Key` header; `?api_key=` still works but ends up in
  proxy logs.
- **Guests** (role 0) see only `public` objects; `login` objects need a user/admin account.
- **Brute force**: direct login is throttled per IP (10 / 15 min), per account + IP
  (5 / 15 min) and per account overall (50 / 15 min); the env admin login per IP and per
  username. Admin actions on users (roles, admin status, deletion, passwords, keys, groups,
  force-logout) are audit-logged; changing another admin or a super admin needs a super admin.
- **Deployment**: bind gunicorn to `127.0.0.1` behind an HTTPS-terminating reverse proxy
  (nginx/Caddy). `ProxyFix` trusts exactly **one** proxy hop (`X-Forwarded-For/Proto/Host`),
  so the proxy must overwrite, not append to, client-supplied forwarding headers and nothing
  else may reach gunicorn directly. Set `APP_BASE_URL` to the public HTTPS URL. Use a
  least-privilege PostgreSQL role instead of `postgres`. Enable HSTS preload only once every
  subdomain is HTTPS.

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
