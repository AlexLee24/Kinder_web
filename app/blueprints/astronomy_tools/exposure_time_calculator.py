"""Astronomy tools, planners, LC plotter, CASTOR ETC, finding chart and the public REST API — exposure_time_calculator (split from astronomy_tools_routes.py)."""
import os
from flask import render_template, request, jsonify, Response
from . import astronomy_tools_bp
from .helpers import _CASTOR_ETC_BODY_PATH, _CASTOR_PRESETS_PATH


@astronomy_tools_bp.route('/exposure_time_calculator')
def exposure_time_calculator():
    # castor_etc_body.html is copied verbatim from CASTOR's src/castorGUI/frontend.
    # It is deliberately read as raw text and injected with `| safe` rather than
    # `{% include %}`d: one of its HTML comments contains a literal example
    # `{% include 'castor_etc_body.html' %}` line, which Jinja would execute if it
    # parsed the file — recursing into the file itself. Injecting raw text mirrors how
    # CASTOR's own server.py mounts the partial, and keeps the file byte-for-byte
    # identical to the engine repo's copy.
    with open(_CASTOR_ETC_BODY_PATH, encoding='utf-8') as f:
        castor_etc_body = f.read()
    return render_template(
        'exposure_time_calculator.html',
        current_path='/exposure_time_calculator',
        castor_etc_body=castor_etc_body,
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
    except Exception as e:
        return jsonify({'error': str(e)}), 400

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
    except Exception as e:
        return jsonify({'error': str(e)}), 400
