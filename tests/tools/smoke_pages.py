"""GET every safe route as four personas (anon / guest / GREAT_Lab member / admin) and
record status, content type, rendered templates and redirect target.

    .venv/bin/python tests/tools/smoke_pages.py OUT.json

Compare two runs (e.g. before and after a refactor) with::

    .venv/bin/python tests/tools/smoke_pages.py --compare BEFORE.json AFTER.json

Needs the live Kinder database. Read-only: only GET requests; routes with side effects
or slow external calls are excluded (see EXCLUDE). Sample IDs (an object with photometry
and spectra, a spectrum id, a comment id, ...) are looked up in the database, so a run is
reproducible as long as those rows still exist.
"""
import glob
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault('DETECT_IN_WEB', '1')

BASE_URL = 'http://localhost:8000'
BP = os.path.join(ROOT, 'app', 'blueprints')

EXCLUDE = {
    '/logout', '/auth/google', '/auth/google/callback',            # auth flow / external
    '/api/object/<object_name>/detect_cross_match',               # GET with side effects (runs DETECT)
    '/api/ned/cone', '/api/finding_chart/image',                  # external network calls
}
RATE_LIMITED_PREFIXES = ('/api/distance', '/api/coords', '/api/date', '/api/finding_chart/surveys',
                         '/api/visibility/image', '/api/objects/')
PERSONAS = {
    'anon': None,
    'guest': {'email': 'smoke-guest@kinder.test', 'name': 'Smoke Guest', 'role': 'guest', 'is_admin': False,
              'is_great_lab_member': False, 'groups': [], 'picture': ''},
    'member': {'email': 'smoke-member@kinder.test', 'name': 'Smoke Member', 'role': 'user', 'is_admin': False,
               'is_great_lab_member': True, 'groups': ['GREAT_Lab'], 'picture': ''},
    'admin': {'email': 'smoke-admin@kinder.test', 'name': 'Smoke Admin', 'role': 'admin', 'is_admin': True,
              'is_great_lab_member': True, 'groups': ['GREAT_Lab'], 'picture': ''},
}


def _samples():
    """Look up sample IDs in the database. Uses autocommit so no transaction stays open
    (an idle transaction would block the app's start-up DDL)."""
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, 'kinder.env'))
    conn = psycopg2.connect(host=os.getenv('PG_HOST'), port=int(os.getenv('PG_PORT', '5432')), database='Kinder',
                            user=os.getenv('PG_USER'), password=os.getenv('PG_PASSWORD'), connect_timeout=5)
    conn.autocommit = True
    cur = conn.cursor()

    def one(sql, params=(), default=None):
        try:
            cur.execute(sql, params)
            r = cur.fetchone()
            return r[0] if r else default
        except Exception:
            return default

    obj = one(r"""select o.name from transient.objects o where o.name ~ '^\d{4}[a-z]+$'
                  and exists(select 1 from transient.photometry p where p.obj_id=o.obj_id)
                  and exists(select 1 from transient.spectroscopy s where s.obj_id=o.obj_id)
                  order by o.discovery_date desc nulls last limit 1""", default='2024ggi')
    obj_id = one("select obj_id from transient.objects where name=%s", (obj,))
    s = {
        'object_name': obj,
        'year': re.match(r'^(\d{4})', obj).group(1), 'letters': obj[4:],
        'target_name': one("select name from transient.target_images order by image_id desc limit 1", default=obj),
        'spectrum_id': str(one("select spec_id from transient.spectroscopy where obj_id=%s limit 1", (obj_id,), 0)),
        'point_id': str(one("select phot_id from transient.photometry where obj_id=%s limit 1", (obj_id,), 0)),
        'comment_id': str(one("select comment_id from transient.comments order by comment_id desc limit 1", default=1)),
        'target_id': str(one("select target_id from obs.targets order by target_id desc limit 1", default=1)),
        'image_id': str(one("select image_id from transient.target_images order by image_id desc limit 1", default=1)),
        'user_email': one("select email from auth.users order by usr_id limit 1", default='x@y.z'),
        'group_name': one("select name from auth.groups order by group_id limit 1", default='GREAT_Lab'),
        'detect_date': one("select to_char(max(run_date),'YYYY-MM-DD') from transient.cross_matches"),
        'request_id': '1', 'action': 'approve',
    }
    cur.close()
    conn.close()

    def first(pattern, default):
        files = sorted(glob.glob(pattern))
        return os.path.basename(files[0]) if files else default

    s['share_id'] = first(os.path.join(ROOT, 'app/data/shared_plots/*.json'), 'none.json')[:-5]
    s['slide'] = first(os.path.join(BP, 'basic/slideshow/*.jpg'), 'x.jpg')
    gal = [f for f in sorted(glob.glob(os.path.join(BP, 'basic/gallery_uploads/*.jpg'))) if '_thumb' not in f]
    s['gallery'] = os.path.basename(gal[0]) if gal else 'x.jpg'
    s['item_id'] = s['gallery'].rsplit('.', 1)[0]
    s['ov'] = first(os.path.join(BP, 'planners/ov_plot/*.jpg'), 'x.jpg')
    s['ep'] = first(os.path.join(BP, 'private_area/data/epessto_uploads/*.asci'), 'x.asci')
    return s


def build_urls(app, s):
    filename_by_rule = {
        '/static/<path:filename>': 'css/_theme.css', '/slideshow/image/<filename>': s['slide'],
        '/gallery/image/<filename>': s['gallery'], '/ov_plot/<path:filename>': s['ov'],
        '/documents/<filename>': 'Test.md', '/api/documents/<filename>/content': 'Test.md',
        '/tutorials/images/<path:filename>': 'nope.png', '/api/epessto_support/image/<path:filename>': s['ep'],
    }

    def fill(rule):
        if rule in filename_by_rule:
            return rule.replace('<filename>', filename_by_rule[rule]).replace('<path:filename>', filename_by_rule[rule])
        return re.sub(r'<([^>]+)>', lambda m: s[m.group(1).split(':')[-1]], rule)

    urls = []
    for r in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if 'GET' not in r.methods or r.rule in EXCLUDE:
            continue
        try:
            urls.append(fill(r.rule))
        except KeyError as e:
            print('skip (no sample for', e, ')', r.rule)
    today = time.strftime('%Y-%m-%d')
    extra = ['/marshal?status=followup', '/marshal?page=2', '/api/objects?limit=5', '/api/objects?status=followup&limit=5',
             f"/detect?detect_results={s['detect_date']}", '/api/target_autocomplete?q=2026', '/api/search_target?q=2026',
             f'/api/log/content?date={today}', f'/api/log/sources?date={today}', '/api/marshal/top-viewed?mode=week',
             '/api/distance?z=0.1', '/api/coords?ra=10.5&dec=-20.25', '/api/date?mjd=60000', '/admin/sources/search?q=ATLAS',
             f'/api/observation_logs?month={today[:7]}', '/api/auto_exposure?mag=18&telescope=LOT&filter=r']
    return list(dict.fromkeys(urls + extra))


def run(out_path):
    from flask import template_rendered
    from app import create_app
    app = create_app(start_jobs=False)
    app.config['TESTING'] = True
    s = _samples()
    urls = build_urls(app, s)
    rendered = []

    def _on_render(sender, template, context, **extra):  # keep a strong reference: blinker holds receivers weakly
        rendered.append(template.name)
    template_rendered.connect(_on_render, app)
    results = {}
    t0 = time.time()
    for pname, user in PERSONAS.items():
        c = app.test_client()
        if user:
            with c.session_transaction() as sess:
                sess['user'] = user
        res = {}
        for u in urls:
            if u.startswith(RATE_LIMITED_PREFIXES):
                time.sleep(1.1)  # public API rate limiter: 1 request/s per endpoint
            rendered.clear()
            t = time.time()
            try:
                r = c.get(u, base_url=BASE_URL)
                body = r.get_data()
                res[u] = {'status': r.status_code, 'ctype': (r.content_type or '').split(';')[0], 'len': len(body),
                          'location': r.headers.get('Location'), 'templates': list(rendered), 'ms': int((time.time() - t) * 1000)}
                if r.status_code >= 500:
                    res[u]['err'] = body[:300].decode('utf-8', 'replace')
            except Exception as e:  # the test client re-raises app exceptions
                res[u] = {'status': 'EXC', 'error': repr(e)[:300], 'templates': list(rendered)}
        results[pname] = res
        counts = {}
        for v in res.values():
            counts[str(v['status'])] = counts.get(str(v['status']), 0) + 1
        print(f'{pname}: {len(res)} urls, statuses: {dict(sorted(counts.items()))}')
    json.dump({'samples': s, 'results': results}, open(out_path, 'w'), indent=1)
    print(f'wrote {out_path} in {time.time() - t0:.0f}s')


def compare(before_path, after_path):
    a = json.load(open(before_path))
    b = json.load(open(after_path))
    diff = total = 0
    for persona in a['results']:
        ra, rb = a['results'][persona], b['results'].get(persona, {})
        for url, va in ra.items():
            total += 1
            vb = rb.get(url)
            if vb is None:
                print('MISSING after:', persona, url)
                diff += 1
                continue
            if any(va.get(k) != vb.get(k) for k in ('status', 'ctype', 'templates', 'location')):
                diff += 1
                print(f"DIFF {persona} {url}: before={va.get('status')} {va.get('ctype')} {va.get('templates')} "
                      f"{va.get('location')} | after={vb.get('status')} {vb.get('ctype')} {vb.get('templates')} {vb.get('location')}")
    print(f'compared {total} (persona,url) pairs: {diff} differences')
    return diff


if __name__ == '__main__':
    if len(sys.argv) >= 4 and sys.argv[1] == '--compare':
        sys.exit(1 if compare(sys.argv[2], sys.argv[3]) else 0)
    run(sys.argv[1] if len(sys.argv) > 1 else 'smoke.json')
    os._exit(0)  # don't wait for background threads
