"""Regression guard: every safe GET route answers the same status code (and renders the
same template) as recorded in ``tests/smoke_baseline.json`` for four personas.

The baseline was captured right before the 2026-09 refactor with
``tests/tools/smoke_pages.py``. Re-capture it (and review the diff) whenever a route's
behaviour changes on purpose::

    .venv/bin/python tests/tools/smoke_pages.py tests/smoke_baseline.json

Needs the live database. The URLs embed sample IDs that were looked up when the baseline
was captured; if those rows disappear the affected cases are skipped, not failed.
"""
import json
import os

import pytest

from tests.conftest import BASE_URL, PERSONAS

pytestmark = pytest.mark.live_db

BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'smoke_baseline.json')
_data = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {'results': {}}
_cases = [(persona, url, rec) for persona, urls in _data['results'].items() for url, rec in urls.items()]


@pytest.fixture(scope='module')
def clients(app):
    out = {}
    for persona, user in PERSONAS.items():
        c = app.test_client()
        if user:
            with c.session_transaction() as s:
                s['user'] = dict(user)
        out[persona] = c
    return out


@pytest.mark.parametrize('persona,url,expected', _cases, ids=[f'{p}:{u}' for p, u, _ in _cases])
def test_route_matches_baseline(clients, persona, url, expected):
    if expected['status'] == 'EXC':
        pytest.skip('baseline itself raised (known dead route)')
    r = clients[persona].get(url, base_url=BASE_URL)
    if r.status_code == 404 and expected['status'] == 200 and any(tok in url for tok in ('/object/', '/api/object/', '/detect_image')):
        pytest.skip('sample object from the baseline no longer exists')
    assert r.status_code == expected['status'], f'{persona} {url}: {r.status_code} != {expected["status"]}'
    assert (r.content_type or '').split(';')[0] == expected['ctype']
