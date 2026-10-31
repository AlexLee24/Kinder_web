"""GET /api/v1/robot/alert — the one endpoint the Lulin observing robot polls (no key, read only).

    curl -s 'https://<kinder>/api/v1/robot/alert'

At most one alert: the newest active, unexpired one, with its ACP ``script`` (+ sha256), or ``"alert": null``.
The robot runs an alert only when its ``id`` is larger than the one it ran last (ids only grow). See app/services/bots/robot.py.
"""
import logging

from flask import jsonify, request

from app.core import rate_limit

from . import astronomy_tools_bp
from .helpers import _client_ip

logger = logging.getLogger(__name__)

POLLS_PER_MINUTE = 60


@astronomy_tools_bp.route('/api/v1/robot/alert', methods=['GET'])
def api_robot_alert():
    ip = _client_ip()
    if not rate_limit.allow(f'robot:{ip}', POLLS_PER_MINUTE, 60):
        resp = jsonify({'error': f'Too many requests: at most {POLLS_PER_MINUTE} per minute.'})
        resp.headers['Retry-After'] = '60'
        return resp, 429
    from app.services.bots import robot
    try:
        body = robot.feed()
    except Exception:
        logger.exception('robot alert feed failed')
        return jsonify({'error': 'Alert unavailable, try again shortly.'}), 503
    robot.note_client(ip, (body['alert'] or {}).get('id'), request.headers.get('User-Agent'))
    resp = jsonify(body)
    resp.headers['Cache-Control'] = 'no-store'
    return resp
