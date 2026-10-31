"""DETECT › LSST-DETECT: DETECT's pages on the LSST alerts DETECT screened
(app/services/lsst/detect.py), alerts without a DESI / Lens candidate left out.

* /detect/lsst                 DETECT's home (detect_home.html via detect_lsst.html): latest run, results,
                               pipeline, with the watch's run panel and LSST-oid cross-match
* /detect/lsst?day=YYYY-MM-DD  DETECT's review page (detect_results.html + detect_results.js)
* /detect/lsst/archives        DETECT's archives (detect_archives.html)

Same cards, verdicts, tags, image and one-key decisions; decisions go to the LSST tables,
never to transient.objects."""
import io
import logging
import re

from flask import flash, jsonify, redirect, render_template, request, send_file, session, url_for

from app.services.lsst import alerce_api
from app.services.lsst import detect as lsst_detect
from app.services.lsst.detect import review_day_for as day_of
from app.services.photometry.data_processing import DataVisualization

from . import detect_bp
from .lsst import _member_api_denied, _member_or_redirect
from .payload import _assemble_detect_payload

logger = logging.getLogger(__name__)

_DAY_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _detect_api() -> dict:
    """window.DETECT_API for detect_results.js on this page."""
    return {
        'setHost':        url_for('detect.lsst_review_set_host'),
        'unsetHost':      url_for('detect.lsst_review_unset_host'),
        'markNoHost':     url_for('detect.lsst_review_mark_no_host'),
        'setStatus':      url_for('detect.lsst_review_set_status'),
        'toggleFlag':     url_for('detect.lsst_review_toggle_flag'),
        'tracker':        url_for('detect.lsst_review_tracker'),
        'lightcurve':     '/api/detect/lsst/review/lightcurve/',
        'fetchPhot':      '/api/detect/lsst/review/fetch_photometry/{name}',
        'fetchPhotLabel': 'Downloading from ALeRCE…',
        'dateUrl':        _day_url(),
        'homeUrl':        url_for('detect.detect_lsst'),
    }


def _day_url() -> str:
    return url_for('detect.detect_lsst') + '?day='


def _links(oid: int, ra, dec, detail: dict | None) -> list[tuple[str, str]]:
    ra_s, dec_s = f'{float(ra):.6f}', f'{float(dec):.6f}'
    links = [('ALeRCE', alerce_api.explorer_url(oid))]
    if detail and detail.get('obj_name'):
        links.append((detail.get('tns_name') or detail['obj_name'], '/object/' + detail['obj_name']))
    links.append(('Sim', url_for('astronomy_tools.telescope_simulator', ra=ra_s, dec=dec_s,
                                 name=lsst_detect.target_name(oid))))
    links.append(('DESI', f'https://www.legacysurvey.org/viewer?ra={ra_s}&dec={dec_s}&zoom=16'
                          f'&mark={ra_s},{dec_s}&layer=ls-dr10-grz&desi-spec-dr1'))
    return links


def _decorate(payload: dict, page_data: dict) -> dict:
    """Per-object links of the LSST page (the template defaults to DETECT's)."""
    details = page_data.get('details_batch') or {}
    for t in payload['results']:
        oid = lsst_detect.oid_from_name(t['target_name'])
        d = details.get(t['target_name'])
        t['obj_href'] = lsst_detect.object_href(d, oid)
        t['image_url'] = url_for('detect.lsst_review_image', oid=oid)
        t['links'] = _links(oid, (d or {}).get('ra'), (d or {}).get('declination'), d) if d else []
    for n in payload['none_list'] + payload['old_list']:
        oid = lsst_detect.oid_from_name(n['target_name'])
        n['obj_href'] = lsst_detect.object_href(details.get(n['target_name']), oid)
    return payload


@detect_bp.route('/detect/lsst/review')
def lsst_review():
    """Old address of the page (it was a separate tab)."""
    return redirect(url_for('detect.detect_lsst', **request.args))


@detect_bp.route('/detect/lsst')
def detect_lsst():
    denied = _member_or_redirect()
    if denied:
        return denied
    metadata = lsst_detect.review_metadata()
    days = metadata['available_dates']
    day = (request.args.get('day') or '').strip()
    oid = request.args.get('oid', type=int)
    missing_oid = None
    if oid and not day:                              # /detect/lsst?oid=… → that alert's day and card
        found = day_of(oid)
        if found in days:
            return redirect(_day_url() + found + f'#t={lsst_detect.target_name(oid)}')
        missing_oid = oid
    if not day:
        return _overview(metadata, missing_oid)
    if not _DAY_RE.match(day) or day not in days:
        flash('Invalid or unknown LSST-DETECT date.', 'error')
        return redirect(url_for('detect.detect_lsst'))
    page_data = lsst_detect.review_page_data(day)
    payload = _assemble_detect_payload(day, metadata=metadata, page_data=page_data,
                                       current_path='/detect/lsst')
    # every LSST alert is new: no "old TNS edits" section
    payload['old_list'], payload['unmatched_recent_days'] = [], None
    payload['counts']['old'] = 0
    return render_template('detect_results.html', page_title='LSST-DETECT', detect_api=_detect_api(),
                           **_decorate(payload, page_data))


def _overview(metadata: dict, missing_oid: int | None):
    """DETECT's home page on LSST: the stat tiles open the newest review day, each top
    alert its own day's card."""
    days = metadata['available_dates']
    overview = lsst_detect.review_overview()
    overview['run_day'] = days[0] if days else None
    for t in overview['top']:
        t['obj_href'] = lsst_detect.object_href(t, t['oid'])
        t['judge_href'] = _day_url() + t['review_day'] + '#t=' + t['name'] if t['review_day'] else None
    return render_template('detect_lsst.html', page_title='LSST-DETECT', current_path='/detect/lsst',
                           latest_date=days[0] if days else None, daily_counts=metadata['daily_counts'],
                           overview=overview, day_url=_day_url(),
                           archives_url=url_for('detect.detect_lsst_archives'),
                           missing_oid=missing_oid,
                           alerce_url=alerce_api.explorer_url(missing_oid) if missing_oid else None)


@detect_bp.route('/detect/lsst/archives')
def detect_lsst_archives():
    denied = _member_or_redirect()
    if denied:
        return denied
    return render_template('detect_archives.html', page_title='LSST-DETECT Archives', day_url=_day_url(),
                           daily_counts=lsst_detect.review_metadata()['daily_counts'],
                           current_path='/detect/lsst/archives')


@detect_bp.route('/detect/lsst/review/image/<int:oid>')
def lsst_review_image(oid):
    if 'user' not in session:
        return 'Unauthorized', 401
    data = lsst_detect.get_image(oid)
    if not data:
        return 'No image', 404
    resp = send_file(io.BytesIO(data), mimetype='image/png')
    resp.headers['Cache-Control'] = 'private, max-age=300'
    return resp


def _oid_or_400(name):
    oid = lsst_detect.oid_from_name(str(name or ''))
    if oid is None:
        return None, (jsonify({'success': False, 'message': 'Not an LSST target name (LSST-<oid>)'}), 400)
    return oid, None


@detect_bp.route('/api/detect/lsst/review/lightcurve/<name>')
def lsst_review_lightcurve(name):
    denied = _member_api_denied()
    if denied:
        return denied
    oid, bad = _oid_or_400(name)
    if bad:
        return bad
    phot, info = lsst_detect.lightcurve_rows(oid)
    if not phot:
        return jsonify({'success': True, 'plot_json': None, 'data_count': 0,
                        'message': 'No LSST photometry stored yet'})
    plot_json = DataVisualization.create_photometry_plot_from_db(
        phot, info.get('z'), info.get('ra'), info.get('dec'), as_json=True)
    return jsonify({'success': True, 'plot_json': plot_json, 'data_count': len(phot), 'cached': False})


@detect_bp.route('/api/detect/lsst/review/fetch_photometry/<name>', methods=['POST'])
def lsst_review_fetch_photometry(name):
    denied = _member_api_denied()
    if denied:
        return denied
    oid, bad = _oid_or_400(name)
    if bad:
        return bad
    try:
        n = lsst_detect.refetch_lightcurve(oid)
    except LookupError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.warning('LSST review light curve %s: %s', oid, e)
        return jsonify({'success': False, 'error': f'ALeRCE did not answer: {e}'}), 502
    return jsonify({'success': True, 'points': n})


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _int(v):
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


@detect_bp.route('/api/detect/lsst/review/set_host', methods=['POST'])
def lsst_review_set_host():
    denied = _member_api_denied()
    if denied:
        return denied
    data = _body()
    oid, bad = _oid_or_400(data.get('target_name'))
    if bad:
        return bad
    match_id = _int(data.get('match_id'))
    status = data.get('status', 'followup')           # 'followup' | 'snoozed' | 'keep'
    if match_id is None or status not in ('followup', 'snoozed', 'keep'):
        return jsonify({'success': False, 'message': 'Missing or invalid parameters'}), 400
    by = session['user'].get('email')
    if not lsst_detect.set_host(oid, match_id, by):
        return jsonify({'success': False, 'message': 'Host candidate not found for this target'}), 404
    if status != 'keep':
        lsst_detect.set_review_status(oid, status, by)
    return jsonify({'success': True})


@detect_bp.route('/api/detect/lsst/review/unset_host', methods=['POST'])
def lsst_review_unset_host():
    denied = _member_api_denied()
    if denied:
        return denied
    oid, bad = _oid_or_400(_body().get('target_name'))
    if bad:
        return bad
    lsst_detect.release_host(oid)
    lsst_detect.set_review_status(oid, 'object', session['user'].get('email'))
    return jsonify({'success': True})


@detect_bp.route('/api/detect/lsst/review/mark_no_host', methods=['POST'])
def lsst_review_mark_no_host():
    denied = _member_api_denied()
    if denied:
        return denied
    oid, bad = _oid_or_400(_body().get('target_name'))
    if bad:
        return bad
    by = session['user'].get('email')
    lsst_detect.reject_hosts(oid, by)
    lsst_detect.set_review_status(oid, 'snoozed', by)
    return jsonify({'success': True})


@detect_bp.route('/api/detect/lsst/review/set_status', methods=['POST'])
def lsst_review_set_status():
    denied = _member_api_denied()
    if denied:
        return denied
    data = _body()
    oid, bad = _oid_or_400(data.get('target_name'))
    if bad:
        return bad
    if data.get('status') not in lsst_detect.REVIEW_STATUSES:
        return jsonify({'success': False, 'message': 'Missing or invalid parameters'}), 400
    if lsst_detect.set_review_status(oid, data['status'], session['user'].get('email')):
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Unknown LSST alert'}), 404


@detect_bp.route('/api/detect/lsst/review/toggle_flag', methods=['POST'])
def lsst_review_toggle_flag():
    denied = _member_api_denied()
    if denied:
        return denied
    data = _body()
    match_id, flag = _int(data.get('id')), data.get('flag')
    if match_id is None or not isinstance(flag, bool):
        return jsonify({'success': False, 'message': 'Missing or invalid parameters'}), 400
    if lsst_detect.set_flag(match_id, flag):
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Database error'})


@detect_bp.route('/api/detect/lsst/review/tracker')
def lsst_review_tracker():
    denied = _member_api_denied()
    if denied:
        return denied
    items = lsst_detect.followup_tracker()
    for it in items:
        it['url'] = url_for('detect.detect_lsst', oid=it['oid'])
    return jsonify({'success': True, 'tracker': items, 'building': False})
