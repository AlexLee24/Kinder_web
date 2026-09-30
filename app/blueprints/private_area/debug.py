"""Private area — debug endpoint (admin only)."""
import logging
from flask import jsonify
from . import private_area_bp
from app.core.auth import admin_required

logger = logging.getLogger(__name__)


# ===============================================================================
# DEBUG ROUTES
# ===============================================================================
@private_area_bp.route('/debug/database')
@admin_required
def debug_database():
    
    try:
        from app.db import get_db_connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM transient.objects")
            total_count = cursor.fetchone()[0]
            cursor.execute("SELECT name_prefix, name, obj_id FROM transient.objects LIMIT 10")
            sample_objects = cursor.fetchall()
            cursor.close()
        return jsonify({
            'total_objects': total_count,
            'sample_objects': [list(r) for r in sample_objects],
        })
        
    except Exception:
        logger.exception('debug_database failed')
        return jsonify({'error': 'Database query failed'}), 500
