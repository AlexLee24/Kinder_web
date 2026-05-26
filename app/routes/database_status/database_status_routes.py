"""Admin database status and connection control routes.

This blueprint is intentionally resilient: the page itself renders without
hitting PostgreSQL, and every status/action API call catches connection
failures so the UI can still open even when the database is down.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, jsonify, render_template, request, redirect, session, url_for

from modules.database import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

logger = logging.getLogger(__name__)

database_status_bp = Blueprint(
    'database_status',
    __name__,
    template_folder='templates',
    static_folder='static',
)


def _is_admin_user() -> bool:
    return 'user' in session and bool(session['user'].get('is_admin', False))


def _db_connect():
    return psycopg2.connect(
        host=DB_HOST,
        port=int(DB_PORT),
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=4,
        application_name='kinder_db_status',
        options='-c statement_timeout=4000',
    )


def _empty_status(error: str | None = None, available: bool = False):
    return {
        'available': available,
        'error': error,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'server': {
            'host': DB_HOST,
            'port': int(DB_PORT),
            'name': DB_NAME,
        },
        'summary': {
            'total': 0,
            'active': 0,
            'idle': 0,
            'idle_in_transaction': 0,
            'waiting': 0,
        },
        'current_pid': None,
        'server_version': None,
        'sessions': [],
    }


def _parse_pids(raw_value):
    if raw_value is None:
        return []
    if isinstance(raw_value, (int, float)):
        return [int(raw_value)]
    if isinstance(raw_value, str):
        raw_items = [x.strip() for x in raw_value.split(',')]
    elif isinstance(raw_value, (list, tuple, set)):
        raw_items = list(raw_value)
    else:
        raw_items = [raw_value]

    pids = []
    for item in raw_items:
        try:
            pid = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if pid > 0:
            pids.append(pid)
    return sorted(set(pids))


def _fetch_status():
    conn = None
    try:
        conn = _db_connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    pg_backend_pid() AS current_pid,
                    version() AS server_version,
                    current_user AS current_user,
                    inet_server_addr()::text AS server_addr,
                    inet_server_port() AS server_port
                """
            )
            meta = cur.fetchone() or {}

            cur.execute(
                """
                SELECT
                    pid,
                    usename,
                    application_name,
                    client_addr::text AS client_addr,
                    client_port,
                    backend_type,
                    state,
                    wait_event_type,
                    wait_event,
                    to_char(xact_start AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS xact_start,
                    to_char(query_start AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS query_start,
                    to_char(state_change AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') AS state_change,
                    GREATEST(0, FLOOR(EXTRACT(EPOCH FROM COALESCE(now() - state_change, interval '0 seconds'))))::int AS state_age_seconds,
                    left(regexp_replace(COALESCE(query, ''), '\\s+', ' ', 'g'), 500) AS query
                FROM pg_stat_activity
                WHERE datname = %s
                ORDER BY
                    CASE WHEN state = 'active' THEN 0 ELSE 1 END,
                    COALESCE(state_change, query_start) DESC NULLS LAST,
                    pid
                """,
                (DB_NAME,),
            )
            sessions = [dict(row) for row in cur.fetchall()]

        summary = {
            'total': len(sessions),
            'active': sum(1 for row in sessions if row.get('state') == 'active'),
            'idle': sum(1 for row in sessions if row.get('state') == 'idle'),
            'idle_in_transaction': sum(1 for row in sessions if row.get('state') == 'idle in transaction'),
            'waiting': sum(1 for row in sessions if row.get('wait_event_type')),
        }

        for row in sessions:
            age = row.get('state_age_seconds') or 0
            row['state_age_seconds'] = int(age)
            row['is_self'] = row.get('pid') == meta.get('current_pid')
            row['client_addr'] = row.get('client_addr') or 'local'
            row['application_name'] = row.get('application_name') or ''
            row['query'] = row.get('query') or ''

        return {
            'available': True,
            'error': None,
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'server': {
                'host': DB_HOST,
                'port': int(DB_PORT),
                'name': DB_NAME,
                'server_addr': meta.get('server_addr'),
                'server_port': meta.get('server_port'),
                'current_user': meta.get('current_user'),
            },
            'summary': summary,
            'current_pid': meta.get('current_pid'),
            'server_version': meta.get('server_version'),
            'sessions': sessions,
        }
    except Exception as exc:
        logger.warning('Database status check failed: %s', exc)
        return _empty_status(str(exc), available=False)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _apply_backend_action(operation: str, pids: list[int]):
    if not pids:
        return {'attempted': 0, 'succeeded': 0, 'failed': 0, 'skipped': 0, 'results': []}

    conn = None
    attempted = succeeded = failed = skipped = 0
    results = []
    try:
        conn = _db_connect()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute('SELECT pg_backend_pid()')
            current_pid = int(cur.fetchone()[0])

            protected = {current_pid}
            for pid in pids:
                attempted += 1
                if pid in protected:
                    skipped += 1
                    results.append({'pid': pid, 'ok': False, 'skipped': True, 'message': 'Cannot terminate the current status session'})
                    continue

                try:
                    if operation == 'cancel':
                        cur.execute('SELECT pg_cancel_backend(%s)', (pid,))
                    else:
                        cur.execute('SELECT pg_terminate_backend(%s)', (pid,))
                    ok = bool(cur.fetchone()[0])
                    if ok:
                        succeeded += 1
                        results.append({'pid': pid, 'ok': True, 'skipped': False, 'message': f'{operation} sent'})
                    else:
                        failed += 1
                        results.append({'pid': pid, 'ok': False, 'skipped': False, 'message': 'Backend refused the request'})
                except Exception as exc:
                    failed += 1
                    results.append({'pid': pid, 'ok': False, 'skipped': False, 'message': str(exc)})

        return {
            'attempted': attempted,
            'succeeded': succeeded,
            'failed': failed,
            'skipped': skipped,
            'results': results,
        }
    except Exception as exc:
        logger.warning('Database backend action failed: %s', exc)
        return {
            'attempted': attempted,
            'succeeded': succeeded,
            'failed': failed + max(1, attempted - succeeded - skipped),
            'skipped': skipped,
            'results': results or [{'pid': None, 'ok': False, 'skipped': False, 'message': str(exc)}],
            'error': str(exc),
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@database_status_bp.route('/admin/database')
def database_status_page():
    if not _is_admin_user():
        return redirect(url_for('basic.home'))
    return render_template('database_status.html', current_path='/admin/database', config_name=DB_NAME)


@database_status_bp.route('/api/admin/database/status')
def api_database_status():
    if not _is_admin_user():
        return jsonify({'error': 'Access denied'}), 403

    payload = _fetch_status()
    status_code = 200 if payload.get('available') else 503
    return jsonify(payload), status_code


@database_status_bp.route('/api/admin/database/action', methods=['POST'])
def api_database_action():
    if not _is_admin_user():
        return jsonify({'error': 'Access denied'}), 403

    data = request.get_json(silent=True) or {}
    operation = str(data.get('operation', 'terminate')).strip().lower()
    if operation not in {'terminate', 'cancel', 'terminate_idle'}:
        return jsonify({'error': 'Invalid operation'}), 400

    if operation == 'terminate_idle':
        try:
            idle_minutes = max(1, min(int(data.get('idle_minutes', 15)), 1440))
        except (TypeError, ValueError):
            return jsonify({'error': 'idle_minutes must be an integer'}), 400

        status = _fetch_status()
        if not status.get('available'):
            return jsonify(status), 503

        conn = None
        try:
            conn = _db_connect()
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pid
                    FROM pg_stat_activity
                    WHERE datname = %s
                      AND pid <> pg_backend_pid()
                      AND backend_type = 'client backend'
                      AND state = 'idle'
                      AND now() - state_change >= make_interval(mins => %s)
                    ORDER BY state_change ASC, pid ASC
                    """,
                    (DB_NAME, idle_minutes),
                )
                target_pids = [int(row[0]) for row in cur.fetchall()]
        except Exception as exc:
            logger.warning('terminate_idle lookup failed: %s', exc)
            return jsonify({'error': str(exc)}), 503
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        result = _apply_backend_action('terminate', target_pids)
        result['operation'] = 'terminate_idle'
        result['idle_minutes'] = idle_minutes
        return jsonify(result)

    pids = _parse_pids(data.get('pids'))
    if not pids:
        return jsonify({'error': 'No pids supplied'}), 400

    result = _apply_backend_action(operation, pids)
    result['operation'] = operation
    result['pids'] = pids
    return jsonify(result)

