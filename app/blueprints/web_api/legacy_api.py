from flask import jsonify, Blueprint

api_blueprint = Blueprint('api', __name__, url_prefix='/api')

@api_blueprint.route('/generate_key', methods=['POST'])
def generate_key():
    return jsonify({
        'error': 'Self-service key generation is disabled. Please request a key from your profile page; an admin will issue it.'
    }), 403
