"""
Marshal routes for the Kinder web application.
"""
from flask import render_template, redirect, url_for, session, flash, request, jsonify

from modules.postgres_database import (
    get_tns_statistics, get_objects_count, search_tns_objects,
    get_tag_statistics
)


from flask import Blueprint
marshal_bp = Blueprint('marshal', __name__, template_folder='templates', static_folder='static')
"""Register marshal routes with the Flask app"""

# ===============================================================================
# MARSHAL
# ===============================================================================
@marshal_bp.route('/marshal')
def marshal():
    from flask import session
    user = session.get('user', {})
    role = user.get('role', 'guest') if user else 'guest'
    is_admin = user.get('is_admin', False) if user else False
    can_see_restricted = is_admin or role in ('user', 'admin')
    visibility = {
        'tags': can_see_restricted,
        'comments_sidebar': can_see_restricted,
    }
    try:
        # Get initial counts for statistics
        total_count = get_objects_count()
        at_count = get_objects_count(object_type='AT')
        classified_count = total_count - at_count
        
        # Get tag-based statistics
        tag_stats = get_tag_statistics()
        
        # Get TNS statistics
        tns_stats = get_tns_statistics()
        
        # Format last sync data properly
        last_sync_data = None
        if tns_stats.get('recent_downloads') and len(tns_stats['recent_downloads']) > 0:
            recent_download = tns_stats['recent_downloads'][0]
            if recent_download.get('download_time'):
                try:
                    raw_time = recent_download['download_time']
                    # Format: "Apr05 20:45:06+08"
                    from datetime import datetime, timezone, timedelta
                    if hasattr(raw_time, 'strftime'):
                        dt = raw_time
                    else:
                        dt_str = str(raw_time)
                        for fmt in ('%Y-%m-%d %H:%M:%S.%f%z', '%Y-%m-%d %H:%M:%S%z',
                                    '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
                            try:
                                dt = datetime.strptime(dt_str[:26], fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            dt = None
                    if dt:
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        tz8 = dt.astimezone(timezone(timedelta(hours=8)))
                        formatted_time = tz8.strftime('%b%d %H:%M:%S+08')
                    else:
                        formatted_time = str(raw_time)[:19]
                    last_sync_data = {
                        'time': formatted_time,
                        'status': 'completed',
                        'imported': recent_download.get('imported_count', 0),
                        'updated': recent_download.get('updated_count', 0)
                    }
                except:
                    pass
        
        # Smart loading strategy for large datasets
        initial_objects = []
        use_api_mode = True  # Default to API mode for large datasets
        initial_limit = 0
        
        # Only load initial data for smaller datasets or specific scenarios
        if total_count <= 1000:
            # Small dataset: load all
            initial_limit = min(total_count, 200)
            use_api_mode = False
        elif total_count <= 5000:
            # Medium dataset: load first page
            initial_limit = 100
            use_api_mode = False
        else:
            # Large dataset: pure API mode, no initial loading
            initial_limit = 0
            use_api_mode = True
        
        # Load initial objects if applicable
        if initial_limit > 0:
            try:
                raw_objects = search_tns_objects(
                    limit=initial_limit, 
                    sort_by='discoverydate', 
                    sort_order='desc'
                )
                
                for obj in raw_objects:
                    if 'tag' not in obj or obj['tag'] is None:
                        obj['tag'] = 'object'
                    initial_objects.append(obj)
                
            except Exception as e:
                # Fallback to API mode if initial loading fails
                initial_objects = []
                use_api_mode = True
        
        return render_template('marshal.html', 
                             current_path='/marshal',
                             objects=initial_objects,
                             tns_stats=tns_stats,
                             at_count=at_count,
                             classified_count=classified_count,
                             inbox_count=tag_stats.get('object', 0),
                             followup_count=tag_stats.get('followup', 0),
                             finished_count=tag_stats.get('finished', 0),
                             snoozed_count=tag_stats.get('snoozed', 0),
                             flag_count=tag_stats.get('flag', 0),
                             last_sync=last_sync_data,
                             total_count=total_count,
                             use_api_mode=use_api_mode,
                             initial_limit=initial_limit,
                             visibility=visibility)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash('Error loading transient data.', 'error')
        return render_template('marshal.html', 
                             current_path='/marshal',
                             objects=[],
                             tns_stats={},
                             at_count=0,
                             classified_count=0,
                             inbox_count=0,
                             followup_count=0,
                             finished_count=0,
                             snoozed_count=0,
                             flag_count=0,
                             last_sync=None,
                             total_count=0,
                             use_api_mode=True,
                             initial_limit=0,
                             visibility=visibility)

@marshal_bp.route('/api/marshal/recent-comments')
def get_marshal_recent_comments():
    try:
        from modules.postgres_database import TNSObjectDB
        comments = TNSObjectDB.get_recent_comments(limit=5)
        # Add formatted date snippet and trim content
        for c in comments:
            if len(c['content']) > 50:
                c['content'] = c['content'][:47] + '...'
        return jsonify({'success': True, 'comments': comments})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@marshal_bp.route('/api/marshal/top-viewed')
def get_marshal_top_viewed():
    try:
        from modules.postgres_database import TNSObjectDB
        mode = request.args.get('mode', '30days')
        targets = TNSObjectDB.get_top_viewed_objects(days=30, limit=5, mode=mode)
        return jsonify({
            'success': True, 
            'targets': targets
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@marshal_bp.route('/api/marshal/pinned-objects')
def get_marshal_pinned_objects():
    if 'user' not in session:
        return jsonify({'success': True, 'objects': []})
    try:
        from modules.postgres_database import get_pinned_objects
        objects = get_pinned_objects(limit=20)
        return jsonify({'success': True, 'objects': objects})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
