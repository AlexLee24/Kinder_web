"""Admin › Site (/admin/site): settings for what the website shows. First section: the sky viewer — which server
Kinder's Aladin views load survey tiles from (CDS / ESA / NASA IRSA; the others are automatic backups), with a live
check of each server and of every survey on each (static/js/admin_site.js + js/hips_fallback.js).
Stored by app/services/aladin_source.py."""
from flask import jsonify, render_template, request

from app.core.auth import admin_required, admin_required_page
from app.services import aladin_source

from . import admin_bp
from .helpers import audit


@admin_bp.route('/admin/site')
@admin_required_page
def site_page():
    return render_template('admin_site.html', current_path='/admin/site',
                           servers=aladin_source.SERVERS, preferred=aladin_source.get_preferred())


@admin_bp.route('/admin/site/aladin', methods=['POST'])
@admin_required
def site_aladin_save():
    data = request.get_json(silent=True) or {}
    key = str(data.get('server') or '').strip().lower()
    if key not in aladin_source.SERVER_KEYS:
        return jsonify({'ok': False, 'error': 'Choose CDS, ESA or IRSA.'}), 400
    before = aladin_source.get_preferred()
    if not aladin_source.set_preferred(key):
        return jsonify({'ok': False, 'error': 'Could not save the setting (database).'}), 500
    audit('site_aladin_server', key, f'from={before}')
    return jsonify({'ok': True, 'config': aladin_source.config()})
