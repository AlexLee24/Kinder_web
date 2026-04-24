"""obs schema — observation targets (obs.targets) and observation logs (obs.logs).

Return dicts use backward-compatible key names matching the legacy kinder_web DB.
"""

import logging
from psycopg2 import extras
from . import get_db_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Observation Targets
# ---------------------------------------------------------------------------

_TARGET_SELECT = (
    "SELECT t.target_id, t.active, t.name, t.mag, t.ra, t.dec, "
    "t.telescope, t.program, t.priority, t.plan_filter, t.plan_count, "
    "t.plan_time, t.repeat, t.plan, t.note, t.create_by, "
    "u.email AS created_by_email "
    "FROM obs.targets t "
    "LEFT JOIN auth.users u ON t.create_by = u.usr_id"
)


def _target_to_dict(row) -> dict:
    d = dict(row)
    # Rebuild filter plan as list of {filter, count, time} for backward compat
    filters = d.pop('plan_filter', None) or []
    counts = d.pop('plan_count', None) or []
    times = d.pop('plan_time', None) or []
    d['filters'] = [
        {'filter': f, 'count': c, 'time': t}
        for f, c, t in zip(filters, counts, times)
    ]
    d['created_by'] = d.pop('created_by_email', None)
    return d


def get_observation_targets(active_only: bool = True) -> list[dict]:
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        if active_only:
            cur.execute(f"{_TARGET_SELECT} WHERE t.active = TRUE ORDER BY t.priority, t.name")
        else:
            cur.execute(f"{_TARGET_SELECT} ORDER BY t.active DESC, t.priority, t.name")
        return [_target_to_dict(r) for r in cur.fetchall()]


def save_observation_target(name: str, ra: float, dec: float,
                             mag: float | None = None,
                             telescope: str = '',
                             program: str = '',
                             priority: str = 'Normal',
                             filters: list | None = None,
                             repeat: int = 0,
                             plan: str = '',
                             note: str = '',
                             created_by_email: str | None = None) -> int | None:
    """Insert or update an observation target.  Returns target_id."""
    plan_filter = []
    plan_count = []
    plan_time = []
    for f in (filters or []):
        if isinstance(f, dict):
            plan_filter.append(f.get('filter', ''))
            plan_count.append(int(f.get('count', 1)))
            plan_time.append(int(f.get('time', 60)))
        else:
            plan_filter.append(str(f))
            plan_count.append(1)
            plan_time.append(60)

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            create_by = None
            if created_by_email:
                cur.execute("SELECT usr_id FROM auth.users WHERE email=%s", (created_by_email,))
                r = cur.fetchone()
                create_by = r[0] if r else None

            cur.execute(
                "INSERT INTO obs.targets "
                "(active, name, mag, ra, dec, telescope, program, priority, "
                " plan_filter, plan_count, plan_time, repeat, plan, note, create_by) "
                "VALUES (TRUE,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (name) DO UPDATE SET "
                "  mag=EXCLUDED.mag, ra=EXCLUDED.ra, dec=EXCLUDED.dec, "
                "  telescope=EXCLUDED.telescope, program=EXCLUDED.program, "
                "  priority=EXCLUDED.priority, plan_filter=EXCLUDED.plan_filter, "
                "  plan_count=EXCLUDED.plan_count, plan_time=EXCLUDED.plan_time, "
                "  repeat=EXCLUDED.repeat, plan=EXCLUDED.plan, note=EXCLUDED.note "
                "RETURNING target_id",
                (name, mag, ra, dec, telescope, program, priority,
                 plan_filter, plan_count, plan_time,
                 repeat, plan, note, create_by)
            )
            target_id = cur.fetchone()[0]
            conn.commit()
        return target_id
    except Exception as e:
        logger.error("save_observation_target %s: %s", name, e)
        return None


def update_observation_target(target_id: int, **kwargs) -> bool:
    """Update fields of an obs.targets row.  Accepts same kwargs as save_observation_target."""
    mapping = {
        'name': 'name', 'mag': 'mag', 'ra': 'ra', 'dec': 'dec',
        'telescope': 'telescope', 'program': 'program', 'priority': 'priority',
        'repeat': 'repeat', 'plan': 'plan', 'note': 'note',
    }
    sets = []
    params = []

    # Handle filters special case
    if 'filters' in kwargs:
        plan_filter, plan_count, plan_time = [], [], []
        for f in kwargs.pop('filters') or []:
            if isinstance(f, dict):
                plan_filter.append(f.get('filter', ''))
                plan_count.append(int(f.get('count', 1)))
                plan_time.append(int(f.get('time', 60)))
            else:
                plan_filter.append(str(f)); plan_count.append(1); plan_time.append(60)
        sets += ['plan_filter=%s', 'plan_count=%s', 'plan_time=%s']
        params += [plan_filter, plan_count, plan_time]

    for k, v in kwargs.items():
        if k in mapping:
            sets.append(f"{mapping[k]} = %s")
            params.append(v)

    if not sets:
        return False
    params.append(target_id)
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE obs.targets SET {', '.join(sets)} WHERE target_id = %s",
                params
            )
            updated = cur.rowcount > 0
            conn.commit()
        return updated
    except Exception as e:
        logger.error("update_observation_target %d: %s", target_id, e)
        return False


def update_observation_target_status(target_id: int, active: bool) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE obs.targets SET active = %s WHERE target_id = %s",
                (active, target_id)
            )
            updated = cur.rowcount > 0
            conn.commit()
        return updated
    except Exception as e:
        logger.error("update_observation_target_status %d: %s", target_id, e)
        return False


def delete_observation_target(target_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM obs.targets WHERE target_id = %s", (target_id,))
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted
    except Exception as e:
        logger.error("delete_observation_target %d: %s", target_id, e)
        return False


# ---------------------------------------------------------------------------
# Observation Logs
# ---------------------------------------------------------------------------

_LOG_SELECT = (
    "SELECT l.log_id, l.target_id, l.date, l.name, l.telescope, "
    "l.program, l.priority, l.repeat, l.trigger_by, "
    "l.trigger, l.observed, "
    "l.trigger_filter, l.trigger_count, l.trigger_time, "
    "l.observed_filter, l.observed_count, l.observed_time, "
    "u.email AS trigger_by_email "
    "FROM obs.logs l "
    "LEFT JOIN auth.users u ON l.trigger_by = u.usr_id"
)


def _log_to_dict(row) -> dict:
    d = dict(row)
    # Rebuild filter arrays as list of {filter, count, time}
    for prefix in ('trigger', 'observed'):
        filters = d.pop(f'{prefix}_filter', None) or []
        counts  = d.pop(f'{prefix}_count', None) or []
        times   = d.pop(f'{prefix}_time', None) or []
        d[f'{prefix}_filters'] = [
            {'filter': f, 'count': c, 'time': t}
            for f, c, t in zip(filters, counts, times)
        ]
    d['triggered_by'] = d.pop('trigger_by_email', None)
    if d.get('date') and hasattr(d['date'], 'strftime'):
        d['date'] = d['date'].strftime('%Y-%m-%d')
    return d


def get_observation_log_months() -> list[str]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT to_char(date, 'YYYY-MM') AS ym "
            "FROM obs.logs ORDER BY ym DESC"
        )
        return [r[0] for r in cur.fetchall()]


def get_observation_logs(month: str | None = None,
                         target_name: str | None = None,
                         telescope: str | None = None) -> list[dict]:
    params = []
    clauses = ['1=1']
    if month:
        clauses.append("to_char(l.date, 'YYYY-MM') = %s"); params.append(month)
    if target_name:
        clauses.append("l.name ILIKE %s"); params.append(f'%{target_name}%')
    if telescope:
        clauses.append("l.telescope = %s"); params.append(telescope)
    where = ' AND '.join(clauses)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(f"{_LOG_SELECT} WHERE {where} ORDER BY l.date DESC, l.log_id DESC", params)
        return [_log_to_dict(r) for r in cur.fetchall()]


def upsert_observation_log(target_id: int, date: str, name: str,
                            telescope: str = '', program: str = '',
                            priority: str = 'Normal', repeat: int = 0,
                            trigger: bool = False, observed: bool = False,
                            trigger_filters: list | None = None,
                            observed_filters: list | None = None,
                            triggered_by_email: str | None = None) -> int | None:
    def _unpack(fl):
        f_list, c_list, t_list = [], [], []
        for item in (fl or []):
            if isinstance(item, dict):
                f_list.append(item.get('filter', ''))
                c_list.append(int(item.get('count', 1)))
                t_list.append(int(item.get('time', 60)))
            else:
                f_list.append(str(item)); c_list.append(1); t_list.append(60)
        return f_list, c_list, t_list

    t_filter, t_count, t_time = _unpack(trigger_filters)
    o_filter, o_count, o_time = _unpack(observed_filters)

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            tby = None
            if triggered_by_email:
                cur.execute("SELECT usr_id FROM auth.users WHERE email=%s", (triggered_by_email,))
                r = cur.fetchone()
                tby = r[0] if r else None

            cur.execute(
                "INSERT INTO obs.logs "
                "(target_id, date, name, telescope, program, priority, repeat, "
                " trigger_by, trigger, observed, "
                " trigger_filter, trigger_count, trigger_time, "
                " observed_filter, observed_count, observed_time) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT ON CONSTRAINT obs_logs_target_date_uniq DO UPDATE SET "
                "  name=EXCLUDED.name, telescope=EXCLUDED.telescope, "
                "  program=EXCLUDED.program, priority=EXCLUDED.priority, "
                "  repeat=EXCLUDED.repeat, trigger_by=EXCLUDED.trigger_by, "
                "  trigger=EXCLUDED.trigger, observed=EXCLUDED.observed, "
                "  trigger_filter=EXCLUDED.trigger_filter, "
                "  trigger_count=EXCLUDED.trigger_count, "
                "  trigger_time=EXCLUDED.trigger_time, "
                "  observed_filter=EXCLUDED.observed_filter, "
                "  observed_count=EXCLUDED.observed_count, "
                "  observed_time=EXCLUDED.observed_time "
                "RETURNING log_id",
                (target_id, date, name, telescope, program, priority, repeat,
                 tby, trigger, observed,
                 t_filter, t_count, t_time,
                 o_filter, o_count, o_time)
            )
            log_id = cur.fetchone()[0]
            conn.commit()
        return log_id
    except Exception as e:
        logger.error("upsert_observation_log: %s", e)
        return None


def delete_observation_log(log_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM obs.logs WHERE log_id = %s", (log_id,))
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted
    except Exception as e:
        logger.error("delete_observation_log %d: %s", log_id, e)
        return False
