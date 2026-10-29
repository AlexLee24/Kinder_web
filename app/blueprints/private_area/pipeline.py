"""Private area: Pipeline — reduction (planned) → photometry with AutoPhOT.

AutoPhOT (the copy in app/vendor/autophot) runs on this server in its own Python;
app/services/pipeline/autophot.py starts it and reads its output. Workspaces live in
the folder AUTOPHOT_RUNS names in kinder.env (see services/pipeline/config.py), one per
target; images are uploaded from the page or copied from the calibrated frames.
"""
import contextlib
import functools
import logging

from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from app.core import rate_limit
from app.services.pipeline import autophot as ap
from app.services.pipeline import calibrated, reduce
from app.services.pipeline import config as pconfig

from . import private_area_bp
from .helpers import can_access_page, user_can_access_page

logger = logging.getLogger(__name__)

PAGE_KEY = 'pipeline'
TABS = ('run', 'results', 'legacy')


def _actor():
    user = session.get('user') or {}
    return user.get('email') or user.get('name') or 'unknown'


def _actor_name():
    user = session.get('user') or {}
    return user.get('name') or user.get('email') or 'unknown'


def _is_admin():
    return bool((session.get('user') or {}).get('is_admin'))


def _page_guard():
    if 'user' not in session:
        flash('Please log in to use the Pipeline.', 'warning')
        return redirect(url_for('basic.login'))
    if not can_access_page(PAGE_KEY):
        flash('Access denied.', 'error')
        return redirect(url_for('basic.home'))
    return None


def _visible(tid, owner=False):
    """The caller's role in a workspace, or 404 when they may not see it (a private one is not even confirmed to exist)."""
    try:
        return ap.require(tid, _actor(), _is_admin(), owner=owner)
    except ap.NotFound:
        abort(404)


def _api(fn=None, *, owner=False, edit=False):
    """JSON API: login + page access (+ access to the workspace in the address; owner=True: its owner only;
    edit=True: the owner, or a member the owner lets change and run it); PipelineError → its message and status."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if 'user' not in session:
                return jsonify({'success': False, 'error': 'Please log in.'}), 401
            if not can_access_page(PAGE_KEY):
                return jsonify({'success': False, 'error': 'Access denied.'}), 403
            try:
                if kwargs.get('tid') is not None:
                    ap.require(kwargs['tid'], _actor(), _is_admin(), owner=owner, edit=edit)
                return fn(*args, **kwargs)
            except ap.NameTaken as e:
                return jsonify({'success': False, 'error': str(e), 'conflict': True, 'name': e.name}), e.status
            except ap.PipelineError as e:
                return jsonify({'success': False, 'error': str(e)}), e.status
            except Exception:
                logger.exception('pipeline API %s failed', request.path)
                return jsonify({'success': False, 'error': 'Something went wrong; see the server log.'}), 500
        return wrapper
    return deco(fn) if fn else deco


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
        ap.sync_telescope_yml()                          # template telescopes this server lacks are added
        ap.cleanup_expired()                             # FITS older than FITS_KEEP_DAYS (at most hourly)
        try:
            workspaces = ap.targets(_actor(), _is_admin())
        except ap.PipelineError as e:
            error = str(e)
    return render_template('pipeline.html', current_path='/pipeline', stage='photometry', stages=pconfig.STAGES,
                           ready=ready, checks=checks, labels={k: v[1] for k, v in pconfig.SETTINGS.items()},
                           workspaces=workspaces, me=_actor(), error=error, upload_chunk=_upload_chunk(),
                           catalogs=ap.CATALOGS, sub_methods=ap.SUB_METHODS, default_catalog=ap.DEFAULT_CATALOG,
                           ts_download=ap.TS_DOWNLOAD, ts_download_labels=ap.TS_DOWNLOAD_LABELS,
                           ts_align=ap.TS_ALIGN, ts_forceconv=ap.TS_FORCECONV, calibrated=calibrated.status(),
                           keep_days=pconfig.FITS_KEEP_DAYS)


@private_area_bp.route('/pipeline/reduction')
def pipeline_reduction():
    guard = _page_guard()
    if guard:
        return guard
    checks, batches, error = [], [], ''
    try:
        checks = reduce.check()
        if all(c['ok'] for c in checks):
            reduce.cleanup_expired()                     # batches older than KEEP_DAYS (at most hourly)
            batches = reduce.batches(_actor(), _is_admin())
    except ap.PipelineError as e:
        error = str(e)
    return render_template('pipeline.html', current_path='/pipeline', stage='reduction', stages=pconfig.STAGES,
                           ready=all(c['ok'] for c in checks) and not error, checks=checks, labels={}, workspaces=[],
                           error=error, batches=batches, upload_chunk=_upload_chunk(), keep_days=reduce.KEEP_DAYS)


def _batch(bid):
    """The batch, or 404 when the caller may not see it (owner and admins only)."""
    try:
        return reduce.require(bid, _actor(), _is_admin())
    except ap.NotFound:
        abort(404)


@private_area_bp.route('/pipeline/reduction/<bid>')
def pipeline_reduction_batch(bid):
    guard = _page_guard()
    if guard:
        return guard
    _batch(bid)
    workspaces = []
    with contextlib.suppress(ap.PipelineError):
        workspaces = [w for w in ap.targets(_actor(), _is_admin()) if w.get('role') in ('owner', 'editor', 'admin')]
    return render_template('pipeline_reduction.html', current_path='/pipeline', stages=pconfig.STAGES,
                           batch=reduce.summary(bid), files=reduce._read(reduce.bdir(bid) / 'batch.json').get('files') or {},
                           types=reduce.TYPES, workspaces=workspaces, keep_days=reduce.KEEP_DAYS,
                           run={**reduce.job(bid), 'results': reduce.results(bid)})


@private_area_bp.route('/pipeline/reduction/<bid>/file/<path:rel>')
def pipeline_reduction_file(bid, rel):
    guard = _page_guard()
    if guard:
        return guard
    _batch(bid)
    try:
        p = reduce.result_path(bid, rel)
    except ap.NotFound:
        abort(404)
    return send_file(p, as_attachment=True, download_name=p.name, mimetype='application/fits')


@private_area_bp.route('/pipeline/reduction/<bid>/results.zip')
def pipeline_reduction_zip(bid):
    guard = _page_guard()
    if guard:
        return guard
    b = _batch(bid)
    try:
        z = reduce.zip_path(bid)
    except ap.NotFound:
        abort(404)
    name = ap.target_id(reduce._name(b)) or bid
    return send_file(z, as_attachment=True, download_name=f'{name}_reduced.zip', mimetype='application/zip')


@private_area_bp.route('/pipeline/telescopes')
def pipeline_telescopes():
    """This server's telescope.yml (topped up from the template in git): what AutoPhOT knows, editable."""
    guard = _page_guard()
    if guard:
        return guard
    synced = ap.sync_telescope_yml()
    try:
        local = str(ap.local_telescope_yml())
    except ap.NotConfigured:
        local = ''
    return render_template('pipeline_telescopes.html', current_path='/pipeline', stages=pconfig.STAGES,
                           rows=ap.telescope_summary(), text=ap.telescope_text(), unset=ap.UNSET, synced=synced,
                           local_path=local, repo_path=str(ap.TELESCOPE_YML.relative_to(ap.REPO)), can_edit=_is_admin())


@private_area_bp.route('/pipeline/telescopes/telescope.yml')
def pipeline_telescopes_download():
    guard = _page_guard()
    if guard:
        return guard
    resp = Response(ap.telescope_text(), mimetype='text/plain')
    resp.headers['Content-Disposition'] = 'attachment; filename="telescope.yml"'  # this server's copy
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
    _visible(tid)
    ap.sync_telescope_yml()
    ap.cleanup_expired()
    try:
        info = ap.info(tid, _actor(), _is_admin())
    except ap.NotFound:
        abort(404)
    tab = request.args.get('tab') or ('results' if info['has_results'] else 'run')
    if tab not in TABS:
        abort(404)
    ctx = {'ap': info, 'tab': tab, 'run': None, 'legacy': None, 'listing': None, 'phot': None, 'images': None,
           'rel': '', 'runs': [], 'imports': []}
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
        ctx['imports'] = ap.imports(tid)
    elif tab == 'legacy':
        ctx['runs'] = ap.legacy_runs(tid)
    ctx['result_links'] = [{**x, 'url': _result_url(x['token'])} for x in info['result_shares']
                           if x['run'] == (request.args.get('run') or '')]
    return render_template('pipeline_workspace.html', current_path='/pipeline', zp_flag_text=ap.zp_flag_text,
                           upload_chunk=_upload_chunk(), me=_actor(),
                           workspaces=sorted(ap.targets(_actor(), _is_admin()), key=lambda w: -w['updated']),
                           catalogs=ap.CATALOGS, sub_methods=ap.SUB_METHODS, default_catalog=ap.DEFAULT_CATALOG,
                           ts_download=ap.TS_DOWNLOAD, ts_download_labels=ap.TS_DOWNLOAD_LABELS,
                           ts_align=ap.TS_ALIGN, ts_forceconv=ap.TS_FORCECONV, calibrated=calibrated.status(),
                           keep_days=info['keep_days'], can_import=_is_admin(),
                           share_url=url_for('private_area.pipeline_share', tid=tid, token=info['share']['token'], _external=True)
                           if info['share'] else '',
                           **ctx)


@private_area_bp.route('/pipeline/share/<tid>/<token>')
def pipeline_share(tid, token):
    """A share link: the person who opens it can use the workspace from then on (it is in their list)."""
    guard = _page_guard()
    if guard:
        return guard
    try:
        ap.join_share(tid, token, _actor())
    except ap.PipelineError:
        flash('This share link is not valid any more. Ask the owner for a new one.', 'warning')
        return redirect(url_for('private_area.pipeline'))
    logger.info('pipeline: %s opened the share link of %s', _actor(), tid)
    return redirect(url_for('private_area.pipeline_workspace', tid=tid, tab='run'))


# ── Results shared by a link: no login, a password the owner chose ──

def _shared_results(token):
    """(workspace id, link) of a results link; 404 when it does not exist (any more)."""
    tid, share = ap.find_result_share(token)
    if not share:
        abort(404)
    return tid, share


def _unlocked(share):
    return bool(session.get(f"pl_res_{share['id']}"))


def _no_store(resp):
    resp.headers['Cache-Control'] = 'private, no-store'
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    return resp


@private_area_bp.route('/pipeline/results/<token>', methods=['GET', 'POST'])
def pipeline_results_public(token):
    tid, share = _shared_results(token)
    run = share.get('run') or None
    if request.method == 'POST':
        if not rate_limit.allow(f'pipeline-results-pw:{share["id"]}:{request.remote_addr or ""}', 10, 600):
            abort(429)
        if ap.check_result_password(share, request.form.get('password', '')):
            session[f"pl_res_{share['id']}"] = True
            return redirect(url_for('private_area.pipeline_results_public', token=token))
        return _no_store(make_response(render_template('pipeline_results_public.html', locked=True, error=True,
                                                       token=token, current_path='/pipeline'), 403))
    if not _unlocked(share):
        return _no_store(make_response(render_template('pipeline_results_public.html', locked=True, error=False,
                                                       token=token, current_path='/pipeline')))
    try:
        info = ap.info(tid)
        legacy = next((r for r in ap.legacy_runs(tid) if r['id'] == run), None) if run else None
        red = ap.run_paths(tid, run)['reduced']
        have = red.is_dir() and any(red.iterdir())
        listing = ap.listing(tid, '', run) if have else None
        phot = ap.photometry(tid, run) if listing is not None else None
        images = ap.image_status(tid, run) if listing is not None else None
    except ap.PipelineError:
        abort(404)
    return _no_store(make_response(render_template(
        'pipeline_results_public.html', locked=False, token=token, current_path='/pipeline', ap=info, run=run, legacy=legacy,
        listing=listing, phot=phot, images=images, zp_flag_text=ap.zp_flag_text)))


@private_area_bp.route('/pipeline/results/<token>/file/<path:rel>')
def pipeline_results_public_file(token, rel):
    """Figures of the shared results (nothing else: no logs, no tables of files)."""
    tid, share = _shared_results(token)
    if not _unlocked(share):
        abort(403)
    try:
        _, p = ap.safe_out(tid, rel, share.get('run') or None)
    except ap.PipelineError:
        abort(404)
    if not p.is_file() or ap.kind(p.name) != 'image':
        abort(404)
    resp = send_file(p, download_name=p.name, max_age=0)
    resp.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    return _no_store(resp)


@private_area_bp.route('/pipeline/results/<token>/export.txt')
def pipeline_results_public_export(token):
    tid, share = _shared_results(token)
    if not _unlocked(share):
        abort(403)
    method = 'AP' if request.args.get('method', 'PSF').upper() == 'AP' else 'PSF'
    try:
        limit = float(request.args.get('limit', 3) or 3)
    except ValueError:
        limit = 3.0
    run = share.get('run') or None
    try:
        text = ap.export_text(tid, method, limit, request.args.get('header', '1') != '0', run)
    except ap.PipelineError:
        abort(404)
    resp = Response(text, mimetype='text/plain')
    if request.args.get('download') == '1':
        resp.headers['Content-Disposition'] = f'attachment; filename="{tid}{"_" + run if run else ""}_{method}_lightcurve.txt"'
    return _no_store(resp)


@private_area_bp.route('/pipeline/autophot/<tid>/file/<path:rel>')
def pipeline_file(tid, rel):
    """A file AutoPhOT wrote: figures and PDFs inline, text as text/plain, ?download=1 as an attachment."""
    guard = _page_guard()
    if guard:
        return guard
    _visible(tid)
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
    _visible(tid)
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
    _visible(tid)
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


@private_area_bp.route('/api/pipeline/autophot/classify', methods=['POST'])
@_api
def pipeline_api_classify():
    """Standard filter of the headers the page read from a folder before uploading it."""
    headers = _body().get('headers')
    if not isinstance(headers, list):
        raise ap.PipelineError('Invalid request.')
    return jsonify({'success': True, 'files': ap.classify(headers)})


@private_area_bp.route('/api/pipeline/autophot/new', methods=['POST'])
@_api
def pipeline_api_new():
    """First page: a named, empty workspace (the page then uploads the images). 409 + conflict when the name is taken."""
    tid = ap.create_workspace(_body(), user=_actor(), user_name=_actor_name())
    logger.info('pipeline: %s created workspace %s', _actor(), tid)
    return jsonify({'success': True, 'id': tid, 'url': url_for('private_area.pipeline_workspace', tid=tid, tab='run')})


@private_area_bp.route('/api/pipeline/autophot/name_check')
@_api
def pipeline_api_name_check():
    """Is the name (+ the user's own ending) free? {'name': what it would be called, 'taken'}."""
    name = ap.final_name(request.args.get('name', ''), request.args.get('suffix', ''))
    return jsonify({'success': True, 'name': name, 'taken': ap.name_taken(name)})


@private_area_bp.route('/api/pipeline/autophot/<tid>/save', methods=['POST'])
@_api(edit=True)
def pipeline_api_save(tid):
    ap.save_target(tid, _body(), user=_actor())
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/share', methods=['POST'])
@_api(owner=True)
def pipeline_api_share(tid):
    token = ap.share_on(tid)['token']
    logger.info('pipeline: %s turned on the share link of %s', _actor(), tid)
    return jsonify({'success': True, 'url': url_for('private_area.pipeline_share', tid=tid, token=token, _external=True)})


@private_area_bp.route('/api/pipeline/autophot/<tid>/share/stop', methods=['POST'])
@_api(owner=True)
def pipeline_api_share_stop(tid):
    ap.share_off(tid)
    logger.info('pipeline: %s stopped sharing %s', _actor(), tid)
    return jsonify({'success': True})


def _pipeline_accounts():
    """{email: user} of the accounts that can open the Pipeline page (a person without an account, or whose account
    cannot see this page, can never run anything)."""
    from app.db.auth import get_users
    return {e: u for e, u in get_users().items() if user_can_access_page(u, PAGE_KEY)}


@private_area_bp.route('/api/pipeline/people')
@_api
def pipeline_api_people():
    """Accounts that can open the Pipeline page, for choosing who may run a workspace: ?q= (2+ letters of a name or email)."""
    q = request.args.get('q', '').strip().lower()
    if len(q) < 2:
        return jsonify({'success': True, 'people': []})
    if not rate_limit.allow(f'pipeline-people:{_actor()}', 60, 300):
        return jsonify({'success': False, 'error': 'Too many searches; wait a few minutes.'}), 429
    people = [{'email': e, 'name': u.get('name') or e} for e, u in _pipeline_accounts().items()
              if e != _actor() and (q in e.lower() or q in str(u.get('name') or '').lower())]
    return jsonify({'success': True, 'people': sorted(people, key=lambda p: p['name'].lower())[:8]})


@private_area_bp.route('/api/pipeline/autophot/<tid>/access', methods=['POST'])
@_api(owner=True)
def pipeline_api_access(tid):
    """Who besides the owner may change and run the workspace: {add: email} / {remove: email} / {run_all: bool}.
    Only an account that can open the Pipeline page can be added."""
    body = _body()
    add = None
    if body.get('add'):
        email = str(body['add']).strip().lower()
        account = next((u for e, u in _pipeline_accounts().items() if e.lower() == email), None)
        if not account:
            raise ap.PipelineError('That person has no account that can open the Pipeline page.')
        add = {'user': account['email'], 'name': account.get('name') or account['email']}
    result = ap.set_run_access(tid, add=add, remove=str(body.get('remove') or '') or None,
                               run_all=bool(body['run_all']) if 'run_all' in body else None)
    logger.info('pipeline: %s changed who may run %s: %s', _actor(), tid, body)
    return jsonify({'success': True, **result})


@private_area_bp.route('/api/pipeline/autophot/<tid>/keep', methods=['POST'])
@_api(owner=True)
def pipeline_api_keep(tid):
    days = ap.keep_one_more_day(tid)
    logger.info('pipeline: %s keeps the images of %s %d days', _actor(), tid, days)
    return jsonify({'success': True, 'keep_days': days})


def _result_url(token):
    return url_for('private_area.pipeline_results_public', token=token, _external=True)


@private_area_bp.route('/api/pipeline/autophot/<tid>/results/share', methods=['POST'])
@_api(owner=True)
def pipeline_api_results_share(tid):
    """A link to one set of results ('run' empty = the current ones), no login, behind the password the owner types."""
    body = _body()
    share = ap.result_share_create(tid, str(body.get('run') or ''), body.get('password'), user=_actor())
    logger.info('pipeline: %s shared the results of %s (run %r)', _actor(), tid, share['run'])
    return jsonify({'success': True, 'id': share['id'], 'url': _result_url(share['token'])})


@private_area_bp.route('/api/pipeline/autophot/<tid>/results/share/stop', methods=['POST'])
@_api(owner=True)
def pipeline_api_results_share_stop(tid):
    ap.result_share_stop(tid, str(_body().get('id') or ''))
    logger.info('pipeline: %s stopped a results link of %s', _actor(), tid)
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/images')
@_api
def pipeline_api_images(tid):
    return jsonify({'success': True, **ap.workspace_images(tid)})


@private_area_bp.route('/api/pipeline/autophot/<tid>/upload', methods=['POST'])
@_api(edit=True)
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
@_api(edit=True)
def pipeline_api_remove_image(tid):
    ap.remove_image(tid, str(_body().get('name') or ''))
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/images/restore', methods=['POST'])
@_api(edit=True)
def pipeline_api_restore_image(tid):
    ap.restore_image(tid, str(_body().get('name') or ''))
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/settings')
@_api
def pipeline_api_settings(tid):
    return jsonify({'success': True, **ap.settings_view(tid)})


@private_area_bp.route('/api/pipeline/autophot/<tid>/run', methods=['POST'])
@_api(edit=True)
def pipeline_api_run(tid):
    ap.start(tid, user=_actor())
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/answer', methods=['POST'])
@_api(edit=True)
def pipeline_api_answer(tid):
    ap.answer(tid, str(_body().get('text') or ''))
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/stop', methods=['POST'])
@_api(edit=True)
def pipeline_api_stop(tid):
    ap.stop(tid)
    logger.info('pipeline: %s stopped AutoPhOT in %s', _actor(), tid)
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/job')
@_api
def pipeline_api_job(tid):
    return jsonify({'success': True, 'job': ap.job(tid)})


@private_area_bp.route('/api/pipeline/autophot/<tid>/delete', methods=['POST'])
@_api(owner=True)
def pipeline_api_delete(tid):
    moved = ap.delete_target(tid)
    logger.info('pipeline: %s deleted workspace %s → %s', _actor(), tid, moved)
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/autophot/<tid>/legacy/delete', methods=['POST'])
@_api(owner=True)
def pipeline_api_legacy_delete(tid):
    ap.delete_legacy(tid, str(_body().get('run') or ''))
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/telescopes', methods=['POST'])
@_api
def pipeline_api_telescopes():
    if not _is_admin():
        raise ap.Forbidden('Only admins can edit telescope.yml.')
    result = ap.save_telescope(_body().get('text', ''), user=_actor())
    return jsonify({'success': True, **result, 'rows': ap.telescope_summary()})


# ── Calibrated frames on this server (reduction pipeline output) ──

@private_area_bp.route('/api/pipeline/calibrated/folders')
@_api
def pipeline_api_calibrated_folders():
    return jsonify({'success': True, **calibrated.folders(request.args.get('q', ''))})


@private_area_bp.route('/api/pipeline/calibrated/folder')
@_api
def pipeline_api_calibrated_folder():
    return jsonify({'success': True, **calibrated.folder(request.args.get('path', ''))})


@private_area_bp.route('/api/pipeline/autophot/<tid>/add_calibrated', methods=['POST'])
@_api(edit=True)
def pipeline_api_add_calibrated(tid):
    """Copy one calibrated frame into the workspace (the page sends them one by one, with progress)."""
    rel = str(_body().get('path') or '')
    result = ap.add_files(tid, [calibrated.file_path(rel)], origin='calibrated:' + rel)
    return jsonify({'success': True, **result})


@private_area_bp.route('/api/pipeline/autophot/<tid>/restore', methods=['POST'])
@_api(edit=True)
def pipeline_api_restore(tid):
    result = ap.restore_expired(tid)
    logger.info('pipeline: %s copied %d expired frames back into %s', _actor(), len(result['added']), tid)
    return jsonify({'success': True, **result})


# ── Import into a Kinder object (admins, like uploads on the object page) ──

def _import_guard():
    user = session.get('user') or {}
    if not user.get('is_admin'):
        raise ap.PipelineError('Only admins can add photometry to Kinder objects.')


@private_area_bp.route('/api/pipeline/autophot/<tid>/import/preview', methods=['POST'])
@_api
def pipeline_api_import_preview(tid):
    _import_guard()
    return jsonify({'success': True, **ap.import_preview(tid, _body())})


@private_area_bp.route('/api/pipeline/autophot/<tid>/import', methods=['POST'])
@_api
def pipeline_api_import(tid):
    _import_guard()
    return jsonify({'success': True, **ap.import_points(tid, _body(), user=_actor())})


@private_area_bp.route('/api/pipeline/autophot/<tid>/import/undo', methods=['POST'])
@_api
def pipeline_api_import_undo(tid):
    _import_guard()
    return jsonify({'success': True, **ap.undo_import(tid, str(_body().get('id') or ''), user=_actor())})


# ── Reduction batches ──

def _bapi(fn):
    """JSON API for a batch: login + page access + the batch is the caller's (or they are an admin)."""
    @functools.wraps(fn)
    @_api
    def wrapper(bid, *args, **kwargs):
        reduce.require(bid, _actor(), _is_admin())
        return fn(bid, *args, **kwargs)
    return wrapper


@private_area_bp.route('/api/pipeline/reduction/new', methods=['POST'])
@_api
def pipeline_api_reduction_new():
    problems = [c['detail'] for c in reduce.check() if not c['ok']]
    if problems:
        raise ap.NotConfigured('Reduction is not set up on this server: ' + '; '.join(problems))
    bid = reduce.create(_actor())
    logger.info('pipeline: %s made reduction batch %s', _actor(), bid)
    return jsonify({'success': True, 'id': bid, 'url': url_for('private_area.pipeline_reduction_batch', bid=bid)})


@private_area_bp.route('/api/pipeline/reduction/<bid>/upload', methods=['POST'])
@_bapi
def pipeline_api_reduction_upload(bid):
    """One piece of a raw frame: bytes in the body; ?name= &offset= &total=."""
    try:
        offset = int(request.args.get('offset', ''))
        total = int(request.args.get('total', ''))
    except ValueError:
        raise ap.PipelineError('Invalid upload.')
    if (request.content_length or 0) > _upload_chunk() + 1024:
        raise ap.PipelineError('Upload piece too large.')
    result = reduce.upload_chunk(bid, request.args.get('name', ''), offset, total, request.get_data(cache=False))
    return jsonify({'success': True, **result})


@private_area_bp.route('/api/pipeline/reduction/<bid>/remove', methods=['POST'])
@_bapi
def pipeline_api_reduction_remove(bid):
    reduce.remove_file(bid, str(_body().get('name') or ''))
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/reduction/<bid>/run', methods=['POST'])
@_bapi
def pipeline_api_reduction_run(bid):
    reduce.start(bid, _actor())
    logger.info('pipeline: %s started reduction batch %s', _actor(), bid)
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/reduction/<bid>/stop', methods=['POST'])
@_bapi
def pipeline_api_reduction_stop(bid):
    reduce.stop(bid)
    logger.info('pipeline: %s stopped reduction batch %s', _actor(), bid)
    return jsonify({'success': True})


@private_area_bp.route('/api/pipeline/reduction/<bid>/job')
@_bapi
def pipeline_api_reduction_job(bid):
    try:
        offset = max(0, int(request.args.get('offset') or 0))
    except ValueError:
        offset = 0
    return jsonify({'success': True, **reduce.job(bid, offset), 'results': reduce.results(bid)})


@private_area_bp.route('/api/pipeline/reduction/<bid>/delete', methods=['POST'])
@_bapi
def pipeline_api_reduction_delete(bid):
    reduce.delete(bid)
    logger.info('pipeline: %s deleted reduction batch %s', _actor(), bid)
    return jsonify({'success': True, 'url': url_for('private_area.pipeline_reduction')})


@private_area_bp.route('/api/pipeline/reduction/<bid>/send', methods=['POST'])
@_bapi
def pipeline_api_reduction_send(bid):
    """Result frames → a Photometry workspace (an existing one, or a new one)."""
    body = _body()
    names = body.get('names')
    if not isinstance(names, list):
        raise ap.PipelineError('Invalid request.')
    got = reduce.send_to_autophot(bid, [str(n) for n in names][:2000], user=_actor(), is_admin=_is_admin(),
                                  tid=str(body.get('workspace') or ''), new_name=str(body.get('name') or ''))
    logger.info('pipeline: %s sent %d frames of reduction batch %s to %s', _actor(), len(got['added']), bid, got['id'])
    return jsonify({'success': True, **got, 'url': url_for('private_area.pipeline_workspace', tid=got['id'], tab='run')})
