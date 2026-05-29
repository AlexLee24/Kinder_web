"""db_monitor.py — Database connection monitor & email alerter.

Checks pool usage + server-side pg_stat_activity every N minutes.
Sends an email when usage crosses WARN or CRIT thresholds.
Registered as a background scheduler job in main.py (production only).
"""

import logging
import os
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Alert thresholds ──────────────────────────────────────────────────────────
WARN_PCT  = 60   # % of pool slots in-use → WARN email
CRIT_PCT  = 85   # % of pool slots in-use → CRITICAL email

# Only send one email per level per cooldown window (avoid spam)
ALERT_COOLDOWN_MINUTES = 30

# ── Recipients ────────────────────────────────────────────────────────────────
ALERT_TO = ["m1139005@gm.astro.ncu.edu.tw"]

# ── Internal state ────────────────────────────────────────────────────────────
_last_alert: dict[str, datetime] = {}   # level → last sent time
_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# SMTP helpers
# ─────────────────────────────────────────────────────────────────────────────

def _smtp_config() -> dict:
    from dotenv import load_dotenv
    basedir = os.path.abspath(os.path.dirname(__file__))
    load_dotenv(os.path.join(basedir, '..', '..', 'kinder.env'), override=True)
    return {
        "server":   os.getenv("SMTP_SERVER", "smtp.gmail.com"),
        "port":     int(os.getenv("SMTP_PORT", "587")),
        "user":     os.getenv("SENDER_EMAIL", ""),
        "password": os.getenv("SENDER_PASSWORD", ""),
    }


def _send_email(subject: str, body: str) -> bool:
    cfg = _smtp_config()
    if not cfg["user"] or not cfg["password"]:
        logger.warning("db_monitor: SMTP credentials not configured, skipping alert.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = cfg["user"]
        msg["To"]      = ", ".join(ALERT_TO)
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(cfg["server"], cfg["port"], timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.login(cfg["user"], cfg["password"])
            s.sendmail(cfg["user"], ALERT_TO, msg.as_string())
        logger.info("db_monitor: alert email sent → %s", ALERT_TO)
        return True
    except Exception as exc:
        logger.error("db_monitor: failed to send email: %s", exc)
        return False


def _should_alert(level: str) -> bool:
    """Return True if cooldown period has passed since last alert at this level."""
    with _lock:
        last = _last_alert.get(level)
        now  = datetime.now(timezone.utc)
        if last is None:
            delta_min = float("inf")
        else:
            delta_min = (now - last).total_seconds() / 60
        if delta_min >= ALERT_COOLDOWN_MINUTES:
            _last_alert[level] = now
            return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Server-side connection query
# ─────────────────────────────────────────────────────────────────────────────

def _query_pg_connections() -> dict:
    """Query pg_stat_activity for server-side connection stats."""
    from modules.database import get_db_connection, DB_USER
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Total connections to this database owned by our user
                cur.execute("""
                    SELECT
                        COUNT(*)                                         AS total,
                        COUNT(*) FILTER (WHERE state = 'active')        AS active,
                        COUNT(*) FILTER (WHERE state = 'idle')          AS idle,
                        COUNT(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_tx
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND usename = %s
                """, (DB_USER,))
                row = cur.fetchone()
                return {
                    "total":       row[0],
                    "active":      row[1],
                    "idle":        row[2],
                    "idle_in_tx":  row[3],
                }
    except Exception as exc:
        logger.warning("db_monitor: could not query pg_stat_activity: %s", exc)
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Main monitor function (called by scheduler)
# ─────────────────────────────────────────────────────────────────────────────

def check_and_alert():
    """Check pool & server connection usage; send email if thresholds exceeded."""
    from modules.database import get_pool_stats

    stats   = get_pool_stats()
    pg_info = _query_pg_connections()
    pct     = stats.get("usage_pct", 0.0)

    logger.info(
        "db_monitor: pool in_use=%d/%d (%.1f%%) | pg active=%s idle=%s idle_in_tx=%s",
        stats.get("in_use", 0), stats.get("pool_max", 0), pct,
        pg_info.get("active", "?"), pg_info.get("idle", "?"),
        pg_info.get("idle_in_tx", "?"),
    )

    # Determine alert level
    if pct >= CRIT_PCT:
        level = "CRITICAL"
        emoji = "🔴"
    elif pct >= WARN_PCT:
        level = "WARNING"
        emoji = "🟡"
    else:
        return  # All good, no alert needed

    if not _should_alert(level):
        logger.debug("db_monitor: %s alert suppressed (cooldown)", level)
        return

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = f"{emoji} Kinder DB {level}: pool {pct:.1f}% in use"
    body = f"""\
{emoji} Kinder Web — Database Connection {level}
Generated: {now_str}

── Pool (psycopg2 ThreadedConnectionPool) ──────────────────
  In-use   : {stats.get('in_use', '?')} / {stats.get('pool_max', '?')}
  Idle      : {stats.get('idle', '?')}
  Usage     : {pct:.1f}%  (WARN≥{WARN_PCT}%  CRIT≥{CRIT_PCT}%)

── Server-side pg_stat_activity ────────────────────────────
  Total     : {pg_info.get('total', '?')}
  Active    : {pg_info.get('active', '?')}
  Idle      : {pg_info.get('idle', '?')}
  Idle in Tx: {pg_info.get('idle_in_tx', '?')}

If pool usage stays high, consider:
  • Restarting gunicorn workers
  • Running: SELECT pg_terminate_backend(pid) FROM pg_stat_activity
             WHERE state = 'idle in transaction' AND datname = 'Kinder';

-- Kinder Web Auto-Monitor
"""
    _send_email(subject, body)

