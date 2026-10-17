"""Private area: Pipeline — reduction (planned) → photometry with AutoPhOT.

AutoPhOT runs on this server in its own Python; app/services/pipeline/autophot.py
starts it and reads its output. The paths are set by an admin in
Admin → Operations → Pipeline. Workspaces live in that folder, one per target;
images are uploaded from the page (or, later, handed over by the Reduction stage).
"""
import functools
import logging

from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from app.core import rate_limit
from app.services.pipeline import autophot as ap
from app.services.pipeline import config as pconfig

from . import private_area_bp
from .helpers import can_access_page

logger = logging.getLogger(__name__)

PAGE_KEY = 'pipeline'
TABS = ('run', 'results', 'legacy')


def _actor():
    user = session.get('user') or {}
    return user.get('email') or user.get('name') or 'unknown'


def _page_guard():
    if 'user' not in session:
        flash('Please log in to use the Pipeline.', 'warning')
        return redirect(url_for('basic.login'))
    if not can_access_page(PAGE_KEY):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    return None


def _api(fn):
    """JSON API: login + page access; PipelineError → its message and status."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'error': 'Please log in.'}), 401
        if not can_access_page(PAGE_KEY):
            return jsonify({'success': False, 'error': 'Access denied.'}), 403
        try:
            return fn(*args, **kwargs)
        except ap.PipelineError as e:
            return jsonify({'success': False, 'error': str(e)}), e.status
        except Exception:
            logger.exception('pipeline API %s failed', request.path)
            return jsonify({'success': False, 'error': 'Something went wrong; see the server log.'}), 500
    return wrapper


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ap.PipelineError('Invalid request.')
    return data


def _upload_chunk():
    """Upload piece size: AutoPhOT's default, but always under this server's request size limit."""
    limit = current_app.config.get('MAX_CONTENT_LENGTH') or ap.UPLOAD_CHUNK * 2
    return max(256 * 1024, min(ap.UPLOAD_CHUNK, limit // 2))


def _setup():
    """(ready, checks) — checks list what is missing for the 'not set up' panel."""
    checks = pconfig.check(probe_python=False)
    return all(c['ok'] for c in checks), checks


# ── Pages ──

@private_area_bp.route('/pipeline')
def pipeline():
    guard = _page_guard()
    if guard:
        return guard
    ready, checks = _setup()
    workspaces, error = [], ''
    if ready:
        try:
            workspaces = ap.targets()
        except ap.PipelineError as e:
            error = str(e)
    return render_template('pipeline.html', current_path='/pipeline', stage='photometry', stages=pconfig.STAGES,
                           ready=ready, checks=checks, labels={k: v[1] for k, v in pconfig.SETTINGS.items()},
                           workspaces=workspaces, error=error, upload_chunk=_upload_chunk(),
                           catalogs=ap.CATALOGS, sub_methods=ap.SUB_METHODS, default_catalog=ap.DEFAULT_CATALOG,
                           ts_download=ap.TS_DOWNLOAD, ts_download_labels=ap.TS_DOWNLOAD_LABELS,
                           ts_align=ap.TS_ALIGN, ts_forceconv=ap.TS_FORCECONV)


@private_area_bp.route('/pipeline/reduction')
def pipeline_reduction():
    guard = _page_guard()
    if guard:
        return guard
    return render_template('pipeline.html', current_path='/pipeline', stage='reduction', stages=pconfig.STAGES,
                           ready=False, checks=[], labels={}, workspaces=[], error='')


@private_area_bp.route('/pipeline/telescopes')
def pipeline_telescopes():
    """The shared telescope.yml: what AutoPhOT knows about each telescope and instrument, editable."""
    guard = _page_guard()
    if guard:
        return guard
    return render_template('pipeline_telescopes.html', current_path='/pipeline', stages=pconfig.STAGES,
                           rows=ap.telescope_summary(), text=ap.telescope_text(), unset=ap.UNSET,
                           repo_path=str(ap.TELESCOPE_YML.relative_to(ap.REPO)))


@private_area_bp.route('/pipeline/telescopes/telescope.yml')
def pipeline_telescopes_download():
    guard = _page_guard()
    if guard:
        return guard
    resp = Response(ap.telescope_text(), mimetype='text/plain')
    resp.headers['Content-Disposition'] = 'attachment; filename="telescope.yml"'
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


@private_area_bp.route('/pipeline/autophot/<tid>')
def pipeline_workspace(tid):
    guard = _page_guard()
    if guard:
        return guard
    ready, _ = _setup()
    if not ready:
        return redirect(url_for('private_area.pipeline'))
    try:
        info = ap.info(tid)
    except ap.NotFound:
        abort(404)
    tab = request.args.get('tab') or ('results' if info['has_results'] else 'run')
    if tab not in TABS:
        abort(404)
    ctx = {'ap': info, 'tab': tab, 'run': None, 'legacy': None, 'listing': None, 'phot': None, 'images': None,
           'rel': '', 'runs': []}
    if tab == 'results':
        run = request.args.get('run') or None
        rel = request.args.get('path', '').strip('/')
        try:
            if run:
                ctx['legacy'] = next((r for r in ap.legacy_runs(tid) if r['id'] == run), None)
                if not ctx['legacy']:
                    abort(404)
                red = ap.run_paths(tid, run)['reduced']
                have, reduced = red.is_dir() and any(red.iterdir()), str(red)
            else:
                have, reduced = info['has_results'], info['reduced']
            ctx.update(run=run, rel=rel, reduced=reduced)
            ctx['listing'] = ap.listing(tid, rel, run) if have else None
            ctx['phot'] = ap.photometry(tid, run) if ctx['listing'] is not None and not rel else None
            ctx['images'] = ap.image_status(tid, run) if not rel else None
        except ap.NotFound:
            abort(404)
    elif tab == 'legacy':
        ctx['runs'] = ap.legacy_runs(tid)
    return render_template('pipeline_workspace.html', current_path='/pipeline', zp_flag_text=ap.zp_flag_text,
                           upload_chunk=_upload_chunk(),
                           catalogs=ap.CATALOGS, sub_methods=ap.SUB_METHODS, default_catalog=ap.DEFAULT_CATALOG,
                           ts_download=ap.TS_DOWNLOAD, ts_download_labels=ap.TS_DOWNLOAD_LABELS,
                           ts_align=ap.TS_ALIGN, ts_forceconv=ap.TS_FORCECONV, **ctx)


@private_area_bp.route('/pipeline/autophot/<tid>/file/<path:rel>')
def pipeline_file(tid, rel):
    """A file AutoPhOT wrote: figures and PDFs inline, text as text/plain, ?download=1 as an attachment."""
    guard = _page_guard()
    if guard:
        return guard
    try:
        _, p = ap.safe_out(tid, rel, request.args.get('run') or None)
    except ap.PipelineError:
        abort(404)
    if not p.is_file():
        abort(404)
    dl = request.args.get('download') == '1'
    k = ap.kind(p.name)
    if not dl and k in ('text', 'csv'):
        resp = Response(p.read_text(errors='replace'), mimetype='text/plain')
    else:
        resp = send_file(p, as_attachment=dl or k in ('fits', 'other'), download_name=p.name, max_age=0)
    # Output is data, never a page: no scripts even when an SVG is opened on its own
    resp.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


@private_area_bp.route('/pipeline/autophot/<tid>/export.txt')
def pipeline_export(tid):
    """Light curve for import: ?method=PSF|AP &limit=3 &header=1|0 &run= ; ?download=1 as an attachment."""
    guard = _page_guard()
    if guard:
        return guard
    method = 'AP' if request.args.get('method', 'PSF').upper() == 'AP' else 'PSF'
    try:
        limit = float(request.args.get('limit', 3) or 3)
    except ValueError:
        limit = 3.0
    run = request.args.get('run') or None
    try:
        text = ap.export_text(tid, method, limit, request.args.get('header', '1') != '0', run)
    except ap.PipelineError:
        abort(404)
    resp = Response(text, mimetype='text/plain')
    resp.headers['Cache-Control'] = 'private, no-store'
    if request.args.get('download') == '1':
        name = f'{tid}{"_" + run if run else ""}_{method}_lightcurve.txt'
        resp.headers['Content-Disposition'] = f'attachment; filename="{name}"'
    return resp


@private_area_bp.route('/pipeline/autophot/<tid>/log')
def pipeline_log(tid):
    guard = _page_guard()
    if guard:
        return guard
    try:
        p = ap.run_paths(tid, request.args.get('run') or None)['log']
    except ap.PipelineError:
        abort(404)
    if not p.is_file():
        abort(404)
    resp = Response(p.read_text(errors='replace'), mimetype='text/plain')
    resp.headers['Cache-Control'] = 'private, no-store'
    return resp


# ── API ──

@private_area_bp.route('/api/pipeline/autophot/resolve')
@_api
def pipeline_api_resolve():
    if not rate_limit.allow(f'pipeline-resolve:{_actor()}', 30, 300):
        return jsonify({'success': False, 'error': 'Too many look-ups; wait a few minutes.'}), 429
    return jsonify({'success': True, **ap.resolve(request.args.get('name', ''))})


@private_area_bp.route('/api/pipeline/autophot/new', methods=['POST'])
@_api
def pipeline_api_new():
    tid = ap.save_target(None, _body(), user=_actor())
    logger.info('pipeline: %s created workspace %s', _actor(), tid)
    return jsonify({'success': True, 'id': tid, 'url': url_for('private_area.pipeline_workspace', tid=tid, tab='run')})


@private_area_bp.route('/api/pipeline/autophot/<tid>/save', methods=['POST'])
@_api
def pipeline_api_save(tid):
    ap.tdir(tid)
    ap.save_target(tid, _body(), user=_actor())
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/images')
@_api
def pipeline_api_images(tid):
    return jsonify({'success': True, **ap.workspace_images(tid)})


@private_area_bp.route('/api/pipeline/autophot/<tid>/upload', methods=['POST'])
@_api
def pipeline_api_upload(tid):
    """One piece of a FITS upload: raw bytes in the body; ?name= &offset= &total= [&template=<filter>]."""
    try:
        offset = int(request.args.get('offset', ''))
        total = int(request.args.get('total', ''))
    except ValueError:
        raise ap.PipelineError('Invalid upload.')
    if (request.content_length or 0) > _upload_chunk() + 1024:
        raise ap.PipelineError('Upload piece too large.')
    result = ap.upload_chunk(tid, request.args.get('name', ''), offset, total, request.get_data(cache=False),
                             template_filter=request.args.get('template', '').strip())
    if result['done']:
        logger.info('pipeline: %s uploaded %s to %s', _actor(), result['name'], tid)
    return jsonify({'success': True, **result})


@private_area_bp.route('/api/pipeline/autophot/<tid>/images/remove', methods=['POST'])
@_api
def pipeline_api_remove_image(tid):
    ap.remove_image(tid, str(_body().get('name') or ''))
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/images/restore', methods=['POST'])
@_api
def pipeline_api_restore_image(tid):
    ap.restore_image(tid, str(_body().get('name') or ''))
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/settings')
@_api
def pipeline_api_settings(tid):
    return jsonify({'success': True, **ap.settings_view(tid)})


@private_area_bp.route('/api/pipeline/autophot/<tid>/run', methods=['POST'])
@_api
def pipeline_api_run(tid):
    ap.start(tid, user=_actor())
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/answer', methods=['POST'])
@_api
def pipeline_api_answer(tid):
    ap.answer(tid, str(_body().get('text') or ''))
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/stop', methods=['POST'])
@_api
def pipeline_api_stop(tid):
    ap.stop(tid)
    logger.info('pipeline: %s stopped AutoPhOT in %s', _actor(), tid)
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/job')
@_api
def pipeline_api_job(tid):
    return jsonify({'success': True, 'job': ap.job(tid)})


@private_area_bp.route('/api/pipeline/autophot/<tid>/delete', methods=['POST'])
@_api
def pipeline_api_delete(tid):
    moved = ap.delete_target(tid)
    logger.info('pipeline: %s deleted workspace %s → %s', _actor(), tid, moved)
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/legacy/delete', methods=['POST'])
@_api
def pipeline_api_legacy_delete(tid):
    ap.delete_legacy(tid, str(_body().get('run') or ''))
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/telescopes', methods=['POST'])
@_api
def pipeline_api_telescopes():
    result = ap.save_telescope(_body().get('text', ''), user=_actor())
    return jsonify({'success': True, **result, 'rows': ap.telescope_summary()})
