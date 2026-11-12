"""Astronomy tools, planners, LC plotter, CASTOR ETC, finding chart and the public REST API — exposure_time_calculator (split from astronomy_tools_routes.py)."""
import os
import logging
from flask import render_template, request, jsonify, Response
from . import astronomy_tools_bp
from .helpers import _CASTOR_ETC_BODY_PATH, _CASTOR_ETC_SIMPLE_BODY_PATH, _CASTOR_PRESETS_PATH

logger = logging.getLogger(__name__)


@astronomy_tools_bp.route('/exposure_time_calculator')
def exposure_time_calculator():
    # castor_etc_body.html (Advanced) and castor_etc_simple_body.html (Simple) are copied
    # verbatim from CASTOR's src/castorGUI/frontend (etc_body.html, etc_simple_body.html).
    # They are deliberately read as raw text and injected with `| safe` rather than
    # `{% include %}`d: one of their HTML comments contains a literal example
    # `{% include 'castor_etc_body.html' %}` line, which Jinja would execute if it
    # parsed the file — recursing into the file itself. Injecting raw text mirrors how
    # CASTOR's own server.py mounts the partials, and keeps the files byte-for-byte
    # identical to the engine repo's copies.
    with open(_CASTOR_ETC_BODY_PATH, encoding='utf-8') as f:
        castor_etc_body = f.read()
    with open(_CASTOR_ETC_SIMPLE_BODY_PATH, encoding='utf-8') as f:
        castor_etc_simple_body = f.read()
    return render_template(
        'exposure_time_calculator.html',
        current_path='/exposure_time_calculator',
        castor_etc_body=castor_etc_body,
        castor_etc_simple_body=castor_etc_simple_body,
    )

@astronomy_tools_bp.route('/api/exposure_time_calculator/presets')
def api_exposure_time_calculator_presets():
    """Thin passthrough of CASTOR's own hardware preset file — no data duplicated here.
    Served as raw bytes (not jsonify) so the file's key order is preserved; Flask's
    jsonify alphabetizes keys by default, which would scramble the intended
    first-listed-is-default preset order."""
    if not os.path.isfile(_CASTOR_PRESETS_PATH):
        return jsonify({'error': 'Presets file not found'}), 404
    with open(_CASTOR_PRESETS_PATH, 'rb') as f:
        return Response(f.read(), mimetype='application/json')

def _castor_validation_error_response(e):
    messages = [
        '{}: {}'.format('.'.join(str(p) for p in err['loc']), err['msg'])
        for err in e.errors()
    ]
    return jsonify({'error': '; '.join(messages) or 'Invalid input'}), 400

@astronomy_tools_bp.route('/api/exposure_time_calculator', methods=['POST'])
def api_exposure_time_calculator():
    from pydantic import ValidationError
    from castor.schema import ObservationRequest
    from castor.calculator import run_calculation

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    try:
        obs_request = ObservationRequest.model_validate(data)
        result = run_calculation(obs_request)
        return jsonify(result.model_dump())
    except ValidationError as e:
        return _castor_validation_error_response(e)
    except Exception:
        logger.exception('exposure time calculation failed')
        return jsonify({'error': 'Calculation failed; check the input values.'}), 400

@astronomy_tools_bp.route('/api/exposure_time_calculator/quick', methods=['POST'])
def api_exposure_time_calculator_quick():
    """Simple mode: hardware + target, then Advanced mode's goals. ``goal: "solve_time"`` (the default) takes
    target_snr and answers with a frame length and count; ``"solve_snr"`` takes single_exp_time and num_exposures
    and answers with the SNR they reach. The planner is CASTOR's (castorCLI/plan.py), as in its own server.py."""
    from pydantic import ValidationError
    from castorCLI import plan, presets

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    goal = data.get('goal') or 'solve_time'
    if goal not in ('solve_time', 'solve_snr'):
        return jsonify({'error': f'Unknown goal {goal!r}: use solve_time or solve_snr.'}), 400
    try:
        ra, dec = plan.parse_coordinates(data.get('ra'), data.get('dec'))
        common = dict(
            site=data.get('site'),
            telescope=data.get('telescope') or None,
            camera=data.get('camera') or None,
            optic_filter=data.get('filter') or None,
            ra=ra, dec=dec,
            mag=float(data['mag']),
            observing_time_utc=data.get('observing_time_utc'),
            fwhm=float(data['fwhm']),
        )
        catalogue = presets.load(_CASTOR_PRESETS_PATH)
        if goal == 'solve_snr':
            result = plan.compute_snr(catalogue, **common,
                                      single_exp_time=float(data['single_exp_time']),
                                      num_exposures=float(data.get('num_exposures', 1)))
        else:
            result = plan.compute_plan(catalogue, **common, target_snr=float(data['target_snr']))
        return jsonify(result)
    except plan.QuickInputError as e:
        return jsonify({'error': str(e)}), 400
    except ValidationError as e:
        return _castor_validation_error_response(e)
    except (KeyError, TypeError, ValueError):
        wanted = 'exposure time' if goal == 'solve_snr' else 'target SNR'
        return jsonify({'error': f'Fill in the magnitude, {wanted} and seeing.'}), 400
    except Exception:
        logger.exception('quick exposure time calculation failed')
        return jsonify({'error': 'Calculation failed; check the input values.'}), 400

@astronomy_tools_bp.route('/api/exposure_time_calculator/batch', methods=['POST'])
def api_exposure_time_calculator_batch():
    from pydantic import ValidationError
    from castor.schema import BatchObservationRequest
    from castor.batch_calculator import run_batch_calculation

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    try:
        batch_request = BatchObservationRequest.model_validate(data)
        result = run_batch_calculation(batch_request)
        return jsonify(result.model_dump())
    except ValidationError as e:
        return _castor_validation_error_response(e)
    except Exception:
        logger.exception('exposure time calculation failed')
        return jsonify({'error': 'Calculation failed; check the input values.'}), 400
