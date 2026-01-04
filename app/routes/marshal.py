"""
Marshal routes for the Kinder web application.
"""
from flask import render_template, redirect, url_for, session, flash, request, jsonify

from modules.postgres_database import (
    get_tns_statistics, get_objects_count, search_tns_objects,
    get_tag_statistics
)


def register_marshal_routes(app):
    """Register marshal routes with the Flask app"""
    
    # ===============================================================================
    # MARSHAL
    # ===============================================================================
    @app.route('/marshal')
    def marshal():
        if 'user' not in session:
            flash('Please log in to access Marshal.', 'warning')
            return redirect(url_for('login'))
        
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
                        last_sync_data = {
                            'time': recent_download['download_time'],
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
                                 last_sync=last_sync_data,
                                 total_count=total_count,
                                 use_api_mode=use_api_mode,
                                 initial_limit=initial_limit)
            
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
                                 last_sync=None,
                                 total_count=0,
                                 use_api_mode=True,
                                 initial_limit=0)
