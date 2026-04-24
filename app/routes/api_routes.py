from flask import jsonify, request, session, Blueprint
from modules.database.auth import generate_api_key_for_user, user_exists

api_blueprint = Blueprint('api', __name__, url_prefix='/api')

@api_blueprint.route('/generate_key', methods=['POST'])
def generate_key():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    email = session['user']['email']
    role = session['user'].get('role', 'guest')
    
    if role == 'guest':
        return jsonify({'error': 'Guests cannot generate API keys. Please contact an admin.'}), 403
        
    if not user_exists(email):
        return jsonify({'error': 'User not found. Please re-login.'}), 404

    try:
        new_key = generate_api_key_for_user(email)
        return jsonify({'success': True, 'api_key': new_key, 'message': 'API Key generated successfully.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
