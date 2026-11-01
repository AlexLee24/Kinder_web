"""DETECT's "checked" marks (app/db/detect_checks.py), for TNS-DETECT (kind 'tns') and LSST-DETECT
(kind 'lsst'): the Check box in the overview's "Highest priority right now", the Check button / C key
on a review card. Host decisions tick it on the server (routes.py, lsst_review.py: mark_seen)."""
from flask import jsonify, request, session

from app.db import detect_checks

from . import detect_bp

_MAX_NAMES = 2000


def _member_denied():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'message': 'Not available for Guest users'}), 403
    return None


def mark_seen(kind: str, name: str) -> None:
    """A host decision on ``name`` also checks it (never fails the decision)."""
    try:
        detect_checks.set_checked(kind, name, True, (session.get('user') or {}).get('email'))
    except Exception:
        pass


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@detect_bp.route('/api/detect/check', methods=['POST'])
def detect_check():
    """{kind: 'tns' | 'lsst', name, checked: bool} → tick / untick."""
    denied = _member_denied()
    if denied:
        return denied
    data = _body()
    kind, name, checked = data.get('kind'), str(data.get('name') or '').strip(), data.get('checked', True)
    if kind not in detect_checks.KINDS or not name or not isinstance(checked, bool):
        return jsonify({'success': False, 'message': 'Missing or invalid parameters'}), 400
    if not detect_checks.set_checked(kind, name, checked, session['user'].get('email')):
        return jsonify({'success': False, 'message': 'Database error'}), 500
    return jsonify({'success': True, 'checked': checked})


@detect_bp.route('/api/detect/checked_state', methods=['POST'])
def detect_checked_state():
    """{kind, names: [...]} → {checked: {name: {checked_by, checked_at}}} (the review page asks once
    on load, since its payload is cached)."""
    denied = _member_denied()
    if denied:
        return denied
    data = _body()
    kind, names = data.get('kind'), data.get('names')
    if kind not in detect_checks.KINDS or not isinstance(names, list):
        return jsonify({'success': False, 'message': 'Missing or invalid parameters'}), 400
    names = [str(n) for n in names[:_MAX_NAMES] if isinstance(n, str)]
    return jsonify({'success': True, 'checked': detect_checks.checked_names(kind, names)})


def overview_lists(kind: str, top: list[dict], load_rows, decorate, limit: int = 8, spare: int = 12,
                   recent: int = 30) -> tuple[list[dict], list[dict]]:
    """The two tabs of the overview's "Highest priority right now".

    to_check: the unchecked rows of ``top`` (DETECT's order): every lens-catalogue one, then ``limit``
    others, then up to ``spare`` more marked ``spare`` (hidden; the page shows one when a row is checked).
    checked: the ``recent`` most recently checked objects of ``kind``, newest first, from
    ``load_rows(names)`` (screen rows in that order), with checked_by / checked_at.
    ``decorate(rows)`` adds obj_href / judge_href to both lists. Rows are copied, never mutated."""
    marks = detect_checks.checked_names(kind, [t['name'] for t in top])
    to_check, others = [], 0
    for t in top:
        if t['name'] in marks:
            continue
        if t.get('has_lens'):
            to_check.append(dict(t))
            continue
        if others >= limit + spare:
            break
        to_check.append({**t, 'spare': others >= limit})
        others += 1
    recent_marks = detect_checks.recent_checked(kind, recent)
    by_name = {m['name']: m for m in recent_marks}
    checked = [{**r, **by_name[r['name']]} for r in load_rows([m['name'] for m in recent_marks])]
    decorate(to_check + checked)
    return to_check, checked
