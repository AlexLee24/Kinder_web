"""DETECT › lens links: /detect/lens/sugohi opens the SuGOHI candidate search (POST only) around a position.

The SuGOHI site has no page per lens and its search form only takes POST, so this page holds the form filled in
(app/services/detect/lens_catalogues.sugohi_search_fields) and submits it. The page sets its own CSP: the site's
form-action allows only this site, and the hook (app/core/hooks.py) keeps a CSP a route has set.
"""
from flask import make_response, render_template_string, request

from app.services.detect import lens_catalogues as lc

from . import detect_bp

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex">
<title>SuGOHI search – Kinder</title></head>
<body style="font-family:system-ui,sans-serif;background:#111;color:#ddd;padding:24px">
<form id="f" method="post" action="{{ action }}">
{% for k, v in fields.items() %}<input type="hidden" name="{{ k }}" value="{{ v }}">{% endfor %}
<p>Opening the SuGOHI lens list around {{ fields.ra0 }}, {{ fields.dec0 }} (radius {{ radius }}″)…</p>
<button type="submit">Open SuGOHI</button></form>
<script>document.getElementById('f').submit();</script></body></html>"""

_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        f"form-action {lc.SUGOHI_SEARCH.split('/~')[0]}; base-uri 'none'; frame-ancestors 'none'")


@detect_bp.app_template_global('lens_describe')
def lens_describe(row):
    """Templates: catalogues, grade / probability and links of one cat.lens row (lens_catalogues.describe)."""
    return lc.describe(row)


@detect_bp.route('/detect/lens/sugohi')
def detect_lens_sugohi():
    try:
        ra, dec = float(request.args['ra']), float(request.args['dec'])
    except (KeyError, TypeError, ValueError):
        return 'ra and dec (degrees) are required', 400
    if not (0 <= ra < 360 and -90 <= dec <= 90):
        return 'ra must be in [0, 360) and dec in [-90, 90]', 400
    resp = make_response(render_template_string(_PAGE, action=lc.SUGOHI_SEARCH, fields=lc.sugohi_search_fields(ra, dec),
                                                 radius=f'{lc.SUGOHI_RADIUS_ARCMIN * 60:g}'))
    resp.headers['Content-Security-Policy'] = _CSP
    resp.headers['Cache-Control'] = 'no-store'
    return resp
