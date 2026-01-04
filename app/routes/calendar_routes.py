"""
Calendar routes for the Kinder web application.
"""
import urllib.parse
from datetime import datetime
from flask import render_template, redirect, url_for, session, flash, request, jsonify, Response

from modules.database import get_users, user_exists, check_object_access
from modules.calendar_database import (
    get_calendar_events, create_calendar_event, update_calendar_event, 
    delete_calendar_event, get_calendar_categories, create_calendar_category
)
from modules.ics_generator import generate_ics_calendar


def register_calendar_routes(app):
    """Register calendar routes with the Flask app"""
    
    # ===============================================================================
    # PRIVATE AREA
    # ===============================================================================
    @app.route('/private')
    def private_area():
        if 'user' not in session:
            flash('Please log in to access private area.', 'warning')
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        
        # Check permissions for 'private_area'
        # Treat 'private_area' as a resource name in the object_permissions table
        if not check_object_access('private_area', user_email):
            flash('Access denied.', 'error')
            return redirect(url_for('home'))
        
        return render_template('private_area.html', current_path='/private')

    @app.route('/private/calendar')
    def private_calendar():
        if 'user' not in session:
            flash('Please log in to access calendar.', 'warning')
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        
        # Check permissions for 'private_area' (calendar is part of private area)
        if not check_object_access('private_area', user_email):
            flash('Access denied.', 'error')
            return redirect(url_for('home'))
            
        return render_template('private_calendar.html', current_path='/private/calendar')

    @app.route('/private/telescope')
    def private_telescope():
        if 'user' not in session:
            flash('Please log in to access telescope management.', 'warning')
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        if not user_exists(user_email):
            flash('Access denied.', 'error')
            return redirect(url_for('home'))
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            flash('Access denied. GREAT Lab members only.', 'error')
            return redirect(url_for('home'))
        
        return render_template('private_telescope.html', current_path='/private/telescope')

    @app.route('/private/projects')
    def private_projects():
        if 'user' not in session:
            flash('Please log in to access projects.', 'warning')
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        if not user_exists(user_email):
            flash('Access denied.', 'error')
            return redirect(url_for('home'))
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            flash('Access denied. GREAT Lab members only.', 'error')
            return redirect(url_for('home'))
        
        return render_template('private_projects.html', current_path='/private/projects')

    @app.route('/private/resources')
    def private_resources():
        if 'user' not in session:
            flash('Please log in to access resources.', 'warning')
            return redirect(url_for('login'))
        
        user_email = session['user']['email']
        if not user_exists(user_email):
            flash('Access denied.', 'error')
            return redirect(url_for('home'))
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            flash('Access denied. GREAT Lab members only.', 'error')
            return redirect(url_for('home'))
        
        return render_template('private_resources.html', current_path='/private/resources')

    # ===============================================================================
    # CALENDAR API ENDPOINTS
    # ===============================================================================
    @app.route('/api/calendar/events')
    def get_calendar_events_api():
        """Get calendar events with optional date filtering"""
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        # Check GREAT Lab membership
        user_email = session['user']['email']
        if not user_exists(user_email):
            return jsonify({'error': 'Access denied'}), 403
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            return jsonify({'error': 'Access denied. GREAT Lab members only'}), 403
        
        try:
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            
            events = get_calendar_events(start_date=start_date, end_date=end_date)
            
            return jsonify({
                'success': True,
                'events': events
            })
            
        except Exception as e:
            app.logger.error(f"Error getting calendar events: {str(e)}")
            return jsonify({'error': 'Failed to get events'}), 500

    @app.route('/api/calendar/events', methods=['POST'])
    def create_calendar_event_api():
        """Create a new calendar event"""
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        # Check GREAT Lab membership
        user_email = session['user']['email']
        if not user_exists(user_email):
            return jsonify({'error': 'Access denied'}), 403
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            return jsonify({'error': 'Access denied. GREAT Lab members only'}), 403
        
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['title', 'start_date', 'end_date']
            for field in required_fields:
                if field not in data or not data[field]:
                    return jsonify({'error': f'Missing required field: {field}'}), 400
            
            # Validate dates
            try:
                start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00'))
                end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00'))
                
                if start_date >= end_date:
                    return jsonify({'error': 'End date must be after start date'}), 400
                    
            except ValueError:
                return jsonify({'error': 'Invalid date format'}), 400
            
            # Create event
            event_data = {
                'title': data['title'],
                'description': data.get('description', ''),
                'start_date': data['start_date'],
                'end_date': data['end_date'],
                'all_day': data.get('all_day', False),
                'location': data.get('location', ''),
                'category': data.get('category'),
                'color': data.get('color', '#007AFF'),
                'created_by': user_email
            }
            
            event_id = create_calendar_event(event_data)
            
            return jsonify({
                'success': True,
                'message': 'Event created successfully',
                'event_id': event_id
            })
            
        except Exception as e:
            app.logger.error(f"Error creating calendar event: {str(e)}")
            return jsonify({'error': 'Failed to create event'}), 500

    @app.route('/api/calendar/events/<int:event_id>', methods=['PUT'])
    def update_calendar_event_api(event_id):
        """Update an existing calendar event"""
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        # Check GREAT Lab membership
        user_email = session['user']['email']
        if not user_exists(user_email):
            return jsonify({'error': 'Access denied'}), 403
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            return jsonify({'error': 'Access denied. GREAT Lab members only'}), 403
        
        try:
            data = request.get_json()
            
            # Validate required fields
            required_fields = ['title', 'start_date', 'end_date']
            for field in required_fields:
                if field not in data or not data[field]:
                    return jsonify({'error': f'Missing required field: {field}'}), 400
            
            # Validate dates
            try:
                start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00'))
                end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00'))
                
                if start_date >= end_date:
                    return jsonify({'error': 'End date must be after start date'}), 400
                    
            except ValueError:
                return jsonify({'error': 'Invalid date format'}), 400
            
            # Update event
            event_data = {
                'title': data['title'],
                'description': data.get('description', ''),
                'start_date': data['start_date'],
                'end_date': data['end_date'],
                'all_day': data.get('all_day', False),
                'location': data.get('location', ''),
                'category': data.get('category'),
                'color': data.get('color', '#007AFF'),
                'updated_by': user_email
            }
            
            if update_calendar_event(event_id, event_data):
                return jsonify({
                    'success': True,
                    'message': 'Event updated successfully'
                })
            else:
                return jsonify({'error': 'Event not found or update failed'}), 404
            
        except Exception as e:
            app.logger.error(f"Error updating calendar event {event_id}: {str(e)}")
            return jsonify({'error': 'Failed to update event'}), 500

    @app.route('/api/calendar/events/<int:event_id>', methods=['DELETE'])
    def delete_calendar_event_api(event_id):
        """Delete a calendar event"""
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        # Check GREAT Lab membership
        user_email = session['user']['email']
        if not user_exists(user_email):
            return jsonify({'error': 'Access denied'}), 403
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            return jsonify({'error': 'Access denied. GREAT Lab members only'}), 403
        
        try:
            if delete_calendar_event(event_id):
                return jsonify({
                    'success': True,
                    'message': 'Event deleted successfully'
                })
            else:
                return jsonify({'error': 'Event not found'}), 404
            
        except Exception as e:
            app.logger.error(f"Error deleting calendar event {event_id}: {str(e)}")
            return jsonify({'error': 'Failed to delete event'}), 500

    @app.route('/api/calendar/categories')
    def get_calendar_categories_api():
        """Get all calendar categories"""
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        # Check GREAT Lab membership
        user_email = session['user']['email']
        if not user_exists(user_email):
            return jsonify({'error': 'Access denied'}), 403
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            return jsonify({'error': 'Access denied. GREAT Lab members only'}), 403
        
        try:
            categories = get_calendar_categories()
            
            return jsonify({
                'success': True,
                'categories': categories
            })
            
        except Exception as e:
            app.logger.error(f"Error getting calendar categories: {str(e)}")
            return jsonify({'error': 'Failed to get categories'}), 500

    @app.route('/api/calendar/categories', methods=['POST'])
    def create_calendar_category_api():
        """Create a new calendar category"""
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        # Check GREAT Lab membership
        user_email = session['user']['email']
        if not user_exists(user_email):
            return jsonify({'error': 'Access denied'}), 403
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            return jsonify({'error': 'Access denied. GREAT Lab members only'}), 403
        
        try:
            data = request.get_json()
            
            # Validate required fields
            if 'name' not in data or not data['name']:
                return jsonify({'error': 'Category name is required'}), 400
            
            if len(data['name'].strip()) < 2:
                return jsonify({'error': 'Category name must be at least 2 characters'}), 400
            
            if len(data['name'].strip()) > 50:
                return jsonify({'error': 'Category name must be less than 50 characters'}), 400
            
            # Create category
            category_data = {
                'name': data['name'].strip(),
                'color': data.get('color', '#007AFF'),
                'description': data.get('description', ''),
                'created_by': user_email
            }
            
            category_id = create_calendar_category(category_data)
            
            return jsonify({
                'success': True,
                'message': 'Category created successfully',
                'category_id': category_id
            })
            
        except Exception as e:
            app.logger.error(f"Error creating calendar category: {str(e)}")
            return jsonify({'error': 'Failed to create category'}), 500

    @app.route('/api/calendar/ics')
    def get_calendar_ics():
        """Generate and return ICS calendar file"""
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        # Check GREAT Lab membership
        user_email = session['user']['email']
        if not user_exists(user_email):
            return jsonify({'error': 'Access denied'}), 403
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            return jsonify({'error': 'Access denied. GREAT Lab members only'}), 403
        
        try:
            # Get all events
            events = get_calendar_events()
            categories = get_calendar_categories()
            
            # Generate ICS content
            ics_content = generate_ics_calendar(events, categories)
            
            # Return as downloadable file
            response = Response(
                ics_content,
                mimetype='text/calendar',
                headers={
                    'Content-Disposition': 'attachment; filename=great_lab_calendar.ics',
                    'Content-Type': 'text/calendar; charset=utf-8'
                }
            )
            
            return response
            
        except Exception as e:
            app.logger.error(f"Error generating ICS calendar: {str(e)}")
            return jsonify({'error': 'Failed to generate calendar'}), 500

    @app.route('/api/calendar/subscribe-url')
    def get_calendar_subscribe_url():
        """Get the subscription URL for the calendar"""
        if 'user' not in session:
            return jsonify({'error': 'Access denied'}), 403
        
        # Check GREAT Lab membership
        user_email = session['user']['email']
        if not user_exists(user_email):
            return jsonify({'error': 'Access denied'}), 403
        
        users = get_users()
        user_data = users.get(user_email, {})
        user_groups = user_data.get('groups', [])
        
        if 'GREAT_Lab' not in user_groups:
            return jsonify({'error': 'Access denied. GREAT Lab members only'}), 403
        
        try:
            base_url = request.url_root.rstrip('/')
            subscribe_url = f"{base_url}/api/calendar/ics"
            
            return jsonify({
                'success': True,
                'subscribe_url': subscribe_url,
                'google_calendar_url': f"https://calendar.google.com/calendar/u/0/r/settings/addbyurl?cid={urllib.parse.quote(subscribe_url)}",
                'instructions': {
                    'google': 'Click Google Calendar link or manually add URL to Google Calendar',
                    'apple': 'Copy subscription URL and select "Subscribe to Calendar" in Apple Calendar',
                    'outlook': 'Copy subscription URL and select "Add Calendar from Internet" in Outlook'
                }
            })
            
        except Exception as e:
            app.logger.error(f"Error getting subscribe URL: {str(e)}")
            return jsonify({'error': 'Failed to get subscribe URL'}), 500

    # ===============================================================================
    # DEBUG ROUTES
    # ===============================================================================
    @app.route('/debug/database')
    def debug_database():
        if 'user' not in session or not session['user'].get('is_admin'):
            return jsonify({'error': 'Access denied'}), 403
        
        try:
            from modules.postgres_database import get_tns_db_connection
            
            conn = get_tns_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM tns_objects")
            total_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT name_prefix, name, objid FROM tns_objects LIMIT 10")
            sample_objects = cursor.fetchall()
            
            cursor.execute("PRAGMA table_info(tns_objects)")
            columns = cursor.fetchall()
            
            conn.close()
            
            return jsonify({
                'total_objects': total_count,
                'sample_objects': sample_objects,
                'columns': [col[1] for col in columns]
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # @app.route('/debug/object/<object_name>')
    # Debug object tag route - disabled (old tns_database function)
    # @app.route('/api/debug-object-tag/<object_name>')
    # def debug_object_tag_route(object_name):
    #     if 'user' not in session or not session['user'].get('is_admin'):
    #         return jsonify({'error': 'Access denied'}), 403
    #     
    #     try:
    #         object_name = urllib.parse.unquote(object_name)
    #         return jsonify({
    #             'success': True,
    #             'object_name': object_name,
    #             'message': 'Debug function disabled - using PostgreSQL now'
    #         })
    #     except Exception as e:
    #         return jsonify({'error': str(e)}), 500
