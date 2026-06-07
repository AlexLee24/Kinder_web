from flask import jsonify, request, session, Blueprint
from modules.database.auth import generate_api_key_for_user, user_exists

api_blueprint = Blueprint('api', __name__, url_prefix='/api')

@api_blueprint.route('/generate_key', methods=['POST'])
def generate_key():
    return jsonify({
        'error': 'Self-service key generation is disabled. Please request a key from your profile page; an admin will issue it.'
    }), 403
