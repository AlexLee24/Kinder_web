"""Object detail page and per-object data APIs (blueprint name 'marshal_bp') — comments (split from object_routes.py)."""
import urllib.parse
from flask import session, request, jsonify
from app.db.transient import TNSObjectDB
from app.db.auth import check_object_access
import logging
from app.core.auth import admin_required, login_required

logger = logging.getLogger(__name__)
from . import objects_bp


# ===============================================================================
# COMMENTS
# ===============================================================================
@objects_bp.route('/api/object/<object_name>/comments')
def get_object_comments(object_name):
    if 'user' not in session:
        return jsonify({'success': True, 'comments': [], 'count': 0})
    
    try:
        object_name = urllib.parse.unquote(object_name)
        
        # Check permissions
        user_email = session['user'].get('email', '')
        if not check_object_access(object_name, user_email):
            return jsonify({
                'success': True,
                'comments': [],
                'count': 0,
                'message': 'Access denied'
            })
        
        # Use PostgreSQL database for comments
        comments = TNSObjectDB.get_comments(object_name)
        
        return jsonify({
            'success': True,
            'comments': comments,
            'count': len(comments)
        })
    except Exception as e:
        logger.error(f"Error getting comments for {object_name}: {str(e)}")
        return jsonify({'error': 'Failed to get comments'}), 500

@objects_bp.route('/api/object/<object_name>/comments', methods=['POST'])
@login_required(error='Access denied', status=403)
def add_object_comment(object_name):
    
    try:
        object_name = urllib.parse.unquote(object_name)
        data = request.get_json()
        content = data.get('content', '').strip()
        
        if not content:
            return jsonify({'error': 'Comment content is required'}), 400
        
        if len(content) > 1000:
            return jsonify({'error': 'Comment is too long (maximum 1000 characters)'}), 400
        
        user = session['user']
        # Use PostgreSQL database for comments
        comment_id = TNSObjectDB.add_comment(
            object_name=object_name,
            user_email=user['email'],
            user_name=user['name'],
            user_picture=user.get('picture', ''),
            content=content
        )
        
        return jsonify({
            'success': True,
            'message': 'Comment added successfully',
            'comment_id': comment_id
        })
        
    except Exception as e:
        logger.error(f"Error adding comment for {object_name}: {str(e)}")
        return jsonify({'error': 'Failed to add comment'}), 500

@objects_bp.route('/api/comments/<int:comment_id>', methods=['DELETE'])
@admin_required
def delete_comment(comment_id):
    
    try:
        # Check if comment exists using PostgreSQL
        comment = TNSObjectDB.get_comment_by_id(comment_id)
        if not comment:
            return jsonify({'error': 'Comment not found'}), 404
        
        if TNSObjectDB.delete_comment(comment_id):
            return jsonify({
                'success': True,
                'message': 'Comment deleted successfully'
            })
        else:
            return jsonify({'error': 'Failed to delete comment'}), 500
    except Exception as e:
        logger.error(f"Error deleting comment {comment_id}: {str(e)}")
        return jsonify({'error': 'Failed to delete comment'}), 500

@objects_bp.route('/api/comments/<int:comment_id>', methods=['PUT', 'PATCH'])
@login_required(error='Access denied', status=403)
def update_comment(comment_id):
        
    try:
        # Check if comment exists
        comment = TNSObjectDB.get_comment_by_id(comment_id)
        if not comment:
            return jsonify({'error': 'Comment not found'}), 404
            
        # Only admin or the comment author can edit
        if not session['user'].get('is_admin') and session['user'].get('email') != comment['user_email']:
            return jsonify({'error': 'Access denied: You can only edit your own comments'}), 403
            
        data = request.get_json()
        content = data.get('content', '').strip()
        
        if not content:
            return jsonify({'error': 'Comment content is required'}), 400
            
        if len(content) > 1000:
            return jsonify({'error': 'Comment is too long (maximum 1000 characters)'}), 400
            
        if TNSObjectDB.update_comment(comment_id, content):
            return jsonify({
                'success': True,
                'message': 'Comment updated successfully'
            })
        else:
            return jsonify({'error': 'Failed to update comment'}), 500
    except Exception as e:
        logger.error(f"Error updating comment {comment_id}: {str(e)}")
        return jsonify({'error': 'Failed to update comment'}), 500
