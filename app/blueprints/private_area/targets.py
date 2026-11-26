"""Private area (GREAT_Lab): Daily Trigger, ePessto++ support, Documents, Lab info, observation targets/logs — targets (split from private_area_routes.py)."""
import logging

from flask import jsonify, request, session

from app.core.auth import login_required
from app.db.obs import (
    _parse_dec_deg,
    _parse_ra_deg,
    delete_observation_target,
    delete_observation_targets,
    get_observation_targets,
    save_observation_target,
    update_observation_target,
)

logger = logging.getLogger(__name__)
from . import private_area_bp
from .helpers import can_access_page


def _coord_error(data):
    """Return a user-facing error string if RA/Dec can't be parsed, else None."""
    try:
        _parse_ra_deg(data.get('ra'))
    except (TypeError, ValueError):
        return 'Invalid RA. Use hh:mm:ss.ss or decimal degrees (e.g. 159.6998).'
    try:
        _parse_dec_deg(data.get('dec'))
    except (TypeError, ValueError):
        return 'Invalid Dec. Use ±dd:mm:ss.ss or decimal degrees (e.g. -12.5).'
    return None


def _auto_exposure(data, telescope):
    """(auto, snr, plan choice, CASTOR result or None, error, camera) for a target being saved: a target with auto
    exposure (SLT or LOT) gets tonight's plan now (and every day after, auto_exposure.update_all), with its camera
    (SLT: Andor934 by default, or Andor936); with no photometry on Kinder and no magnitude typed it cannot use auto
    exposure."""
    from app.services.planning import auto_exposure as ae
    telescope = telescope if telescope in ae.CAMERAS else 'SLT'
    auto = bool(data.get('auto_exposure', False))
    # its own camera, or None: the one the telescope last used (auto_exposure.last_camera), resolved at each plan
    camera = data.get('auto_camera') if data.get('auto_camera') in ae.CAMERAS[telescope] else None
    raw = str(data.get('auto_snr') if data.get('auto_snr') is not None else '').strip().lower()
    snr = None                         # blank / auto: from the target's brightness (auto_exposure.auto_snr)
    if raw not in ('', 'auto', '0'):
        try:
            snr = float(raw)
        except ValueError:
            snr = 0
        if not 3 <= snr <= 500:
            return auto, None, None, None, 'Target S/N must be a number between 3 and 500, or blank for auto.', camera
    choice = ','.join(ae.selection(data.get('auto_plan')))
    mags_set = ae.clean_mags(data.get('auto_mags') if isinstance(data.get('auto_mags'), dict) else {})
    if not auto:
        return False, snr, choice, None, None, camera
    try:
        res = ae.compute(data.get('name'), _parse_ra_deg(data.get('ra')), _parse_dec_deg(data.get('dec')),
                         None, snr, choice, telescope=telescope, camera=camera, mags_set=mags_set)   # typed: MAG column only
    except ae.NoMagnitude as e:
        return auto, snr, choice, None, str(e), camera
    except Exception:
        logger.exception('auto exposure for %s', data.get('name'))
        return auto, snr, choice, None, 'Could not compute the auto exposure plan (CASTOR).', camera
    return auto, snr, choice, res, None, camera


def ae_mags(data):
    """The magnitudes typed per filter in the form (blank: automatic), as stored on the target."""
    from app.services.planning.auto_exposure import clean_mags
    return clean_mags(data.get('auto_mags') if isinstance(data.get('auto_mags'), dict) else {}) or None


def _store_auto_result(target_id, res):
    from app.db.obs import set_auto_exposure_result
    from app.services.planning.auto_exposure import latest_mag
    if res is not None:
        set_auto_exposure_result(target_id, res, filters=res['plan'] or None, mag=latest_mag(res))


@private_area_bp.route('/api/targets', methods=['GET', 'POST'])
@login_required
def api_observation_targets():

    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)

    if request.method == 'GET':
        if not can_access_page('daily_trigger'):
            return jsonify({'error': 'Access denied'}), 403
        targets = get_observation_targets(active_only=False)
        return jsonify({'success': True, 'targets': targets})

    elif request.method == 'POST':
        if not (is_great_lab or is_admin):
            return jsonify({'error': 'Forbidden'}), 403

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({'error': 'Invalid JSON body'}), 400
        _err = _coord_error(data)
        if _err:
            return jsonify({'error': _err}), 400
        _telescope = (data.get('telescope') or '').strip().upper()
        _auto_exp, _snr, _choice, _res, _aerr, _cam = _auto_exposure(data, _telescope)
        if _aerr:
            return jsonify({'error': _aerr}), 400
        new_id = save_observation_target(
            telescope=data.get('telescope'),
            name=data.get('name'),
            mag=data.get('mag'),
            ra=data.get('ra'),
            dec=data.get('dec'),
            priority=data.get('priority'),
            repeat_count=data.get('repeat_count', 0),
            auto_exposure=_auto_exp,
            auto_snr=_snr,
            auto_plan=_choice,
            auto_camera=_cam,
            auto_mags=ae_mags(data),
            filters=data.get('filters', []),
            plan=data.get('plan'),
            program=data.get('program'),
            note_gl=data.get('note_gl', ''),
            user_email=session['user']['email']
        )

        if new_id:
            _store_auto_result(new_id, _res)
            return jsonify({'success': True, 'id': new_id, 'auto_result': _res})
        else:
            return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/<int:target_id>', methods=['DELETE'])
@login_required
def api_observation_target_delete(target_id):

    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403

    if delete_observation_target(target_id):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/bulk_delete', methods=['POST'])
@login_required
def api_observation_targets_bulk_delete():
    if not (session['user'].get('is_great_lab_member', False) or session['user'].get('is_admin', False)):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True)
    raw = data.get('ids') if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw or len(raw) > 500:
        return jsonify({'error': 'ids must be a non-empty list'}), 400
    try:
        ids = [int(i) for i in raw]
    except (TypeError, ValueError):
        return jsonify({'error': 'ids must be integers'}), 400
    n = delete_observation_targets(ids)
    if n < 0:
        return jsonify({'error': 'Database error'}), 500
    return jsonify({'success': True, 'deleted': n})

@private_area_bp.route('/api/targets/<int:target_id>/toggle', methods=['PUT'])
@login_required
def api_observation_target_toggle(target_id):

    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403

    data = request.json
    is_active = data.get('is_active')
    if is_active is None:
        return jsonify({'error': 'is_active field required'}), 400

    from app.db.obs import update_observation_target_status
    if update_observation_target_status(target_id, bool(is_active)):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/<int:target_id>/keep', methods=['PUT'])
@login_required
def api_observation_target_keep(target_id):
    """Keep a switched-off target: it is not deleted automatically after obs.OFF_DAYS."""
    if not (session['user'].get('is_great_lab_member', False) or session['user'].get('is_admin', False)):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or 'keep' not in data:
        return jsonify({'error': 'keep field required'}), 400
    from app.db.obs import set_observation_target_keep
    if set_observation_target_keep(target_id, bool(data['keep'])):
        return jsonify({'success': True})
    return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/<int:target_id>', methods=['PUT'])
@login_required
def api_observation_target_update(target_id):

    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400
    _err = _coord_error(data)
    if _err:
        return jsonify({'error': _err}), 400
    _tele_put = (data.get('telescope') or '').strip().upper()
    _auto_exp_put, _snr, _choice, _res, _aerr, _cam = _auto_exposure(data, _tele_put)
    if _aerr:
        return jsonify({'error': _aerr}), 400
    if update_observation_target(
        target_id=target_id,
        telescope=data.get('telescope'),
        name=data.get('name'),
        mag=data.get('mag'),
        ra=data.get('ra'),
        dec=data.get('dec'),
        priority=data.get('priority'),
        repeat_count=data.get('repeat_count', 0),
        auto_exposure=_auto_exp_put,
        auto_snr=_snr,
        auto_plan=_choice,
        auto_camera=_cam,
        auto_mags=ae_mags(data),
        filters=data.get('filters', []),
        plan=data.get('plan'),
        program=data.get('program'),
        note_gl=data.get('note_gl', '')
    ):
        _store_auto_result(target_id, _res)
        return jsonify({'success': True, 'auto_result': _res})
    else:
        return jsonify({'error': 'Database error'}), 500

@private_area_bp.route('/api/targets/update-mags', methods=['POST'])
@login_required
def api_update_target_mags():

    is_great_lab = session['user'].get('is_great_lab_member', False)
    is_admin = session['user'].get('is_admin', False)
    if not (is_great_lab or is_admin):
        return jsonify({'error': 'Forbidden'}), 403

    import threading

    from app.services.photometry.phot_scheduler import update_target_mags

    def _run():
        update_target_mags()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': 'Magnitude update started'})

def _lsst_search_results(q, seen):
    """LSST objects from DETECT › LSST whose oid matches q ("LSST-1711…" or plain digits). One that
    already has a TNS name is offered under that name, so the target is created as the TNS object."""
    from app.services.lsst import alerts as lsst_alerts
    out = []
    for a in lsst_alerts.search_alerts(q):
        if a['obj_name']:
            prefix, name, kind = a['name_prefix'] or '', a['obj_name'], a['obj_type'] or 'AT'
        else:
            prefix, name, kind = '', f"{lsst_alerts.TRIGGER_PREFIX}{a['oid']}", f"LSST {a['class_name'] or ''}".strip()
        if prefix + name in seen:
            continue
        seen.add(prefix + name)
        out.append({'name': name, 'prefix': prefix, 'ra': a['ra'], 'dec': a['dec'], 'mag': None,
                    'type': kind, 'internal_names': f"LSST oid {a['oid']}", 'lsst_oid': str(a['oid']),
                    'reporting_group': '', 'source_group': '', 'redshift': None})
    return out


@private_area_bp.route('/api/search_target')
@login_required
def api_search_target():
    """Search TNS objects by name for autocomplete"""

    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'results': []})

    try:
        from app.db.transient import search_tns_objects
        rows = search_tns_objects(search_term=q, limit=15, sort_by='discoverydate', sort_order='desc',
                                  apply_permissions=True,
                                  viewer_email=session['user'].get('email') or None,
                                  viewer_is_admin=bool(session['user'].get('is_admin')))
        try:                    # Newest Mag: the latest detection, as the daily update and auto exposure use
            from app.services.planning.auto_exposure import latest_by_object
            latest = latest_by_object([r['name'] for r in rows])
        except Exception:
            logger.exception('latest magnitudes for the target search')
            latest = {}
        results = []
        for r in rows:
            results.append({
                'name': r['name'],
                'prefix': r.get('name_prefix') or '',
                'reporting_group': r.get('reporting_group') or '',
                'source_group': r.get('source_group') or '',
                'ra': r.get('ra'),
                'dec': r.get('declination'),
                'redshift': r.get('redshift'),
                'mag': latest.get(r['name']) or r.get('brightest_mag') or r.get('discoverymag'),
                'type': r.get('type') or '',
                'internal_names': r.get('internal_names') or '',
            })
        results.extend(_lsst_search_results(q, {(r['prefix'] + r['name']) for r in results}))
        return jsonify({'results': results})
    except Exception as e:
        logger.error('Search error: %s', e)
        return jsonify({'results': []})

@private_area_bp.route('/api/auto_exposure', methods=['POST'])
@login_required
def api_auto_exposure():
    """Tonight's CASTOR auto exposure plan for the target form (not saved): {name, ra, dec, mag, auto_snr,
    auto_plan} -> the result of app.services.planning.auto_exposure.compute."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid JSON body'}), 400
    _err = _coord_error(data)
    if _err:
        return jsonify({'error': _err}), 400
    from app.services.planning import auto_exposure as ae
    tel = (data.get('telescope') or 'SLT').strip().upper()
    _, _, _, res, err, _ = _auto_exposure({**data, 'auto_exposure': True}, tel)
    if err:
        return jsonify({'error': err}), 400
    try:          # what the telescope last used (all filters of a night share one camera), and this target's last night
        res['last'] = {'telescope': ae.last_frames(res['telescope']),
                       'target': ae.last_frames(res['telescope'], data.get('name')) if data.get('name') else None}
    except Exception:
        logger.exception('last frames for %s', data.get('name'))
    return jsonify({'success': True, 'result': res})
