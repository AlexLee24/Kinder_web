"""obs schema — observation targets (obs.targets) and observation logs (obs.logs).

Return dicts use backward-compatible key names matching the legacy kinder_web DB.
"""

import logging
from datetime import date as _date
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
    # obs.targets stores exposure seconds in plan_count and repeats in plan_time.
    filters = d.pop('plan_filter', None) or []
    counts = d.pop('plan_count', None) or []
    times = d.pop('plan_time', None) or []
    d['filters'] = [
        {'filter': f, 'count': t, 'time': c, 'exp': c}
        for f, c, t in zip(filters, counts, times)
    ]
    d['created_by'] = d.pop('created_by_email', None)
    d['id'] = d.get('target_id')
    d['is_active'] = d.get('active', True)
    d['repeat_count'] = d.get('repeat', 0)
    d['note_gl'] = d.get('note')
    # Return ra/dec as strings to preserve precision and ensure consistent typing
    if d.get('ra') is not None:
        d['ra'] = str(d['ra'])
    if d.get('dec') is not None:
        d['dec'] = str(d['dec'])
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
                             created_by_email: str | None = None,
                             **legacy_kwargs) -> int | None:
    """Insert or update an observation target.  Returns target_id."""
    if legacy_kwargs.get('repeat_count') is not None:
        repeat = int(legacy_kwargs.get('repeat_count') or 0)
    if legacy_kwargs.get('note_gl') is not None:
        note = legacy_kwargs.get('note_gl') or ''
    if legacy_kwargs.get('user_email') and not created_by_email:
        created_by_email = legacy_kwargs.get('user_email')

    plan_filter = []
    plan_count = []
    plan_time = []
    for f in (filters or []):
        if isinstance(f, dict):
            plan_filter.append(f.get('filter', ''))
            plan_count.append(int(f.get('exp', f.get('time', 60)) or 60))
            plan_time.append(int(f.get('count', 1) or 1))
        else:
            plan_filter.append(str(f))
            plan_count.append(60)
            plan_time.append(1)

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
                plan_count.append(int(f.get('exp', f.get('time', 60)) or 60))
                plan_time.append(int(f.get('count', 1) or 1))
            else:
                plan_filter.append(str(f)); plan_count.append(60); plan_time.append(1)
        sets += ['plan_filter=%s', 'plan_count=%s', 'plan_time=%s']
        params += [plan_filter, plan_count, plan_time]

    if 'repeat_count' in kwargs and 'repeat' not in kwargs:
        kwargs['repeat'] = kwargs.pop('repeat_count')
    if 'note_gl' in kwargs and 'note' not in kwargs:
        kwargs['note'] = kwargs.pop('note_gl')
    kwargs.pop('auto_exposure', None)

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
    "u.email AS trigger_by_email, "
    "t_obj.name AS target_name "
    "FROM obs.logs l "
    "LEFT JOIN auth.users u ON l.trigger_by = u.usr_id "
    "LEFT JOIN obs.targets t_obj ON l.target_id = t_obj.target_id"
)


def _log_to_dict(row) -> dict:
    d = dict(row)
    # obs.logs stores exposure seconds in *_count and repeats in *_time.
    for prefix in ('trigger', 'observed'):
        filters = d.pop(f'{prefix}_filter', None) or []
        counts  = d.pop(f'{prefix}_count', None) or []
        times   = d.pop(f'{prefix}_time', None) or []
        rebuilt_filters = [
            {'filter': f, 'count': t, 'time': c, 'exp': c}
            for f, c, t in zip(filters, counts, times)
        ]
        d[f'{prefix}_filters'] = rebuilt_filters
        d[f'{prefix}_filter'] = ','.join(str(x.get('filter', '')) for x in rebuilt_filters if x.get('filter')) or None
        d[f'{prefix}_count'] = ','.join(str(x.get('count', '')) for x in rebuilt_filters if x.get('filter')) or None
        d[f'{prefix}_exp'] = ','.join(str(x.get('exp', '')) for x in rebuilt_filters if x.get('filter')) or None
    d['triggered_by'] = d.pop('trigger_by_email', None)
    if d.get('date') and hasattr(d['date'], 'strftime'):
        d['date'] = d['date'].strftime('%Y-%m-%d')
    d['obs_date'] = d.get('date')
    # target_name: prefer JOIN result from obs.targets; fall back to denormalized l.name
    d['target_name'] = d.pop('target_name', None) or d.get('name')
    d['telescope_use'] = d.get('telescope')
    d['repeat_count'] = d.get('repeat', 0)
    d['is_triggered'] = d.get('trigger', False)
    d['is_observed'] = d.get('observed', False)
    d['user_name'] = d.get('triggered_by')
    return d


def get_observation_log_months() -> list[dict]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT EXTRACT(YEAR FROM date)::int AS year, "
            "EXTRACT(MONTH FROM date)::int AS month "
            "FROM obs.logs ORDER BY year DESC, month DESC"
        )
        return [{'year': r[0], 'month': r[1]} for r in cur.fetchall()]


def get_observation_logs(year_or_month: int | str | None = None,
                         month: int | str | None = None,
                         target_name: str | None = None,
                         telescope: str | None = None) -> list[dict]:
    month_key = None
    if isinstance(year_or_month, str) and month is None:
        month_key = year_or_month
    elif year_or_month is not None and month is not None:
        month_key = f"{int(year_or_month):04d}-{int(month):02d}"
    elif year_or_month is None and isinstance(month, str):
        month_key = month

    params = []
    clauses = ['1=1']
    if month_key:
        # Use a sargable date-range comparison so PostgreSQL can use an index on obs.logs(date).
        # to_char() on the left side of = would make the column non-indexable.
        try:
            y_m, m_m = int(month_key[:4]), int(month_key[5:7])
            next_y, next_m = (y_m + 1, 1) if m_m == 12 else (y_m, m_m + 1)
            clauses.append("l.date >= %s AND l.date < %s")
            params.extend([_date(y_m, m_m, 1), _date(next_y, next_m, 1)])
        except Exception:
            clauses.append("to_char(l.date, 'YYYY-MM') = %s")
            params.append(month_key)
    if target_name:
        clauses.append("t_obj.name ILIKE %s"); params.append(f'%{target_name}%')
    if telescope:
        clauses.append("l.telescope = %s"); params.append(telescope)
    where = ' AND '.join(clauses)
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(f"{_LOG_SELECT} WHERE {where} ORDER BY l.date DESC, l.log_id DESC", params)
        return [_log_to_dict(r) for r in cur.fetchall()]


def _split_csv(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip() and str(x).strip().lower() != 'none']
    text = str(raw).strip()
    if not text or text.lower() == 'none':
        return []
    return [x.strip() for x in text.split(',') if x.strip() and x.strip().lower() != 'none']


def _coerce_log_filters(filter_value, exp_value=None, count_value=None) -> list[dict]:
    if not filter_value:
        return []
    if isinstance(filter_value, list):
        if filter_value and isinstance(filter_value[0], dict):
            return [
                {
                    'filter': str(x.get('filter', '')).strip(),
                    'exp': int(x.get('exp', x.get('time', 0)) or 0),
                    'count': int(x.get('count', 1) or 1),
                }
                for x in filter_value if x and str(x.get('filter', '')).strip()
            ]
        filters = _split_csv(filter_value)
    else:
        try:
            import json as _json
            parsed = _json.loads(filter_value) if isinstance(filter_value, str) else None
            if isinstance(parsed, list):
                return _coerce_log_filters(parsed, exp_value, count_value)
        except Exception:
            pass
        filters = _split_csv(filter_value)

    exp_list = _split_csv(exp_value)
    count_list = _split_csv(count_value)
    rows = []
    for idx, filt in enumerate(filters):
        exp_raw = exp_list[idx] if idx < len(exp_list) else (exp_list[0] if len(exp_list) == 1 else None)
        count_raw = count_list[idx] if idx < len(count_list) else (count_list[0] if len(count_list) == 1 else None)
        rows.append({
            'filter': filt,
            'exp': int(exp_raw or 0),
            'count': int(count_raw or 1),
        })
    return rows


def _resolve_target_id(cur, target_name: str, telescope: str = '') -> int | None:
    if telescope:
        cur.execute(
            "SELECT target_id FROM obs.targets WHERE name = %s AND telescope = %s ORDER BY active DESC, target_id DESC LIMIT 1",
            (target_name, telescope)
        )
        row = cur.fetchone()
        if row:
            return row[0]
    cur.execute(
        "SELECT target_id FROM obs.targets WHERE name = %s ORDER BY active DESC, target_id DESC LIMIT 1",
        (target_name,)
    )
    row = cur.fetchone()
    return row[0] if row else None


def upsert_observation_log(target_id_or_name, date: str, name_or_user: str,
                            *args, **kwargs) -> int | None:
    def _unpack(fl):
        f_list, c_list, t_list = [], [], []
        for item in (fl or []):
            if isinstance(item, dict):
                f_list.append(item.get('filter', ''))
                c_list.append(int(item.get('exp', item.get('time', 0)) or 0))
                t_list.append(int(item.get('count', 1) or 1))
            else:
                f_list.append(str(item)); c_list.append(0); t_list.append(1)
        return f_list, c_list, t_list

    if isinstance(target_id_or_name, int):
        target_id = target_id_or_name
        _target_name_for_lookup = ''  # not needed when target_id is known
        name = kwargs.get('name', '')
        telescope = kwargs.get('telescope', kwargs.get('telescope_use', '')) or ''
        program = kwargs.get('program', '') or ''
        priority = kwargs.get('priority', 'Normal') or 'Normal'
        repeat = int(kwargs.get('repeat', kwargs.get('repeat_count', 0)) or 0)
        trigger = bool(kwargs.get('trigger', False))
        observed = bool(kwargs.get('observed', False))
        trigger_filters = kwargs.get('trigger_filters') or []
        observed_filters = kwargs.get('observed_filters') or []
        triggered_by_value = kwargs.get('triggered_by_email')
    else:
        _target_name_for_lookup = str(target_id_or_name).strip()
        # obs.logs.name is denormalized target name (per schema); observer goes into trigger_by FK
        name = _target_name_for_lookup
        target_id = None
        telescope = kwargs.get('telescope', kwargs.get('telescope_use', '')) or ''
        program = kwargs.get('program', '') or ''
        priority = kwargs.get('priority', 'Normal') or 'Normal'
        repeat = int(kwargs.get('repeat', kwargs.get('repeat_count', 0)) or 0)
        triggered_by_value = name_or_user

        trigger = bool(args[0]) if len(args) > 0 else bool(kwargs.get('trigger', kwargs.get('is_triggered', False)))
        observed = bool(args[1]) if len(args) > 1 else bool(kwargs.get('observed', kwargs.get('is_observed', False)))
        if len(args) >= 7:
            trigger_filters = _coerce_log_filters(args[2], args[3], args[4])
            observed_filters = _coerce_log_filters(args[5], args[6], args[7] if len(args) > 7 else None)
        else:
            trigger_filters = kwargs.get('trigger_filters') or _coerce_log_filters(
                kwargs.get('trigger_filter'), kwargs.get('trigger_exp'), kwargs.get('trigger_count')
            )
            observed_filters = kwargs.get('observed_filters') or _coerce_log_filters(
                kwargs.get('observed_filter'), kwargs.get('observed_exp'), kwargs.get('observed_count')
            )

    t_filter, t_count, t_time = _unpack(trigger_filters)
    o_filter, o_count, o_time = _unpack(observed_filters)

    # Normalize priority to title case to avoid DB CHECK constraint violation
    _VALID_PRI = {'urgent': 'Urgent', 'high': 'High', 'normal': 'Normal', 'filler': 'Filler'}
    if priority:
        priority = _VALID_PRI.get(str(priority).strip().lower(), str(priority).strip().title())
    if not priority:
        priority = 'Normal'

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            tby = None
            if triggered_by_value:
                cur.execute(
                    "SELECT usr_id FROM auth.users WHERE email=%s OR name=%s LIMIT 1",
                    (triggered_by_value, triggered_by_value)
                )
                r = cur.fetchone()
                tby = r[0] if r else None

            if target_id is None:
                target_id = _resolve_target_id(cur, _target_name_for_lookup, telescope)

            if target_id is not None:
                # Update existing row by (name, date, telescope) first to avoid unique-key conflicts.
                cur.execute(
                    "SELECT log_id FROM obs.logs WHERE name = %s AND date = %s AND telescope = %s LIMIT 1",
                    (name, date, telescope)
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        "UPDATE obs.logs SET "
                        "  target_id=%s, program=%s, priority=%s, repeat=%s, "
                        "  trigger_by=%s, trigger=%s, observed=%s, "
                        "  trigger_filter=%s, trigger_count=%s, trigger_time=%s, "
                        "  observed_filter=%s, observed_count=%s, observed_time=%s "
                        "WHERE log_id=%s RETURNING log_id",
                        (target_id, program, priority, repeat,
                         tby, trigger, observed,
                         t_filter, t_count, t_time,
                         o_filter, o_count, o_time,
                         existing[0])
                    )
                else:
                    cur.execute(
                        "INSERT INTO obs.logs "
                        "(target_id, date, name, telescope, program, priority, repeat, "
                        " trigger_by, trigger, observed, "
                        " trigger_filter, trigger_count, trigger_time, "
                        " observed_filter, observed_count, observed_time) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "RETURNING log_id",
                        (target_id, date, name, telescope, program, priority, repeat,
                         tby, trigger, observed,
                         t_filter, t_count, t_time,
                         o_filter, o_count, o_time)
                    )
            else:
                # Target not in obs.targets — save orphan log (target_id=NULL).
                # Do manual upsert by (name, date, telescope) to align with current unique constraint.
                logger.warning("upsert_observation_log: target '%s' not in obs.targets, saving orphan log", name)
                cur.execute(
                    "SELECT log_id FROM obs.logs WHERE name = %s AND date = %s AND telescope = %s",
                    (name, date, telescope)
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        "UPDATE obs.logs SET "
                        "  telescope=%s, program=%s, priority=%s, repeat=%s, "
                        "  trigger_by=%s, trigger=%s, observed=%s, "
                        "  trigger_filter=%s, trigger_count=%s, trigger_time=%s, "
                        "  observed_filter=%s, observed_count=%s, observed_time=%s "
                        "WHERE log_id=%s RETURNING log_id",
                        (telescope, program, priority, repeat,
                         tby, trigger, observed,
                         t_filter, t_count, t_time,
                         o_filter, o_count, o_time,
                         existing[0])
                    )
                else:
                    cur.execute(
                        "INSERT INTO obs.logs "
                        "(target_id, date, name, telescope, program, priority, repeat, "
                        " trigger_by, trigger, observed, "
                        " trigger_filter, trigger_count, trigger_time, "
                        " observed_filter, observed_count, observed_time) "
                        "VALUES (NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "RETURNING log_id",
                        (date, name, telescope, program, priority, repeat,
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


def delete_observation_log(log_id_or_name, obs_date: str | None = None,
                           telescope: str | None = None) -> bool:
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            if isinstance(log_id_or_name, int):
                cur.execute("DELETE FROM obs.logs WHERE log_id = %s", (log_id_or_name,))
            else:
                if not obs_date:
                    return False
                # log_id_or_name is target_name; resolve to target_id first
                target_id = _resolve_target_id(cur, str(log_id_or_name), telescope or '')
                if target_id is None:
                    return False
                cur.execute(
                    "DELETE FROM obs.logs WHERE target_id = %s AND date = %s",
                    (target_id, obs_date)
                )
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted
    except Exception as e:
        logger.error("delete_observation_log %s: %s", log_id_or_name, e)
        return False
