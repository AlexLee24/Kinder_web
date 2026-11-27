"""Privacy policy (/privacy) and terms of service (/terms), in English and 繁體中文.

The text lives in templates/legal/<doc>_<lang>.html; the facts that are still open live in FACTS below, so
settling one is a one-line edit here. A fact set to None shows on the page as a "to be confirmed" mark.
Language: ?lang=en|zh, else the browser's preferred language (Chinese → zh), else English.
"""
from flask import abort, render_template, request

from .routes import basic_bp

UPDATED = '2026-11-27'

FACTS = {
    'email_user': 'kinder', 'email_domain': 'astro.ncu.edu.tw',   # the address in the home footer
    'log_days': 3,              # how long server logs are kept, in days
    'delete_days': 3,           # days after an account is deleted until its personal data is gone
    'acknowledgement': None,    # suggested acknowledgement sentence for papers (None: not shown)
}

DOCS = {
    'privacy': {'en': 'Privacy Policy', 'zh': '隱私權政策'},
    'terms': {'en': 'Terms of Service', 'zh': '服務條款'},
}
LANGS = ('en', 'zh')


def _lang() -> str:
    asked = (request.args.get('lang') or '').lower()
    if asked in LANGS:
        return asked
    best = request.accept_languages.best_match(['en', 'zh-TW', 'zh'], default='en')
    return 'zh' if best.startswith('zh') else 'en'


def _render(doc: str):
    if doc not in DOCS:
        abort(404)
    lang = _lang()
    return render_template('legal.html', doc=doc, lang=lang, docs=DOCS, facts=FACTS, updated=UPDATED,
                           current_path=f'/{doc}')


@basic_bp.route('/privacy')
def privacy():
    return _render('privacy')


@basic_bp.route('/terms')
def terms():
    return _render('terms')
