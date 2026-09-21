"""Object detail page and per-object data APIs (blueprint name 'marshal_bp') — page (split from object_routes.py)."""
import re
import urllib.parse
from datetime import datetime
from flask import render_template, redirect, url_for, session, flash
from app.db.transient import search_tns_objects, TNSObjectDB, update_object_abs_mag
from app.db import get_tns_db_connection, OBJECT_COMPAT_COLS
from . import objects_bp


# ===============================================================================
# OBJECT DETAILS
# ===============================================================================
@objects_bp.route('/object/<path:object_name>')
def object_detail_generic(object_name):
    """Generic object detail route for all object names"""
    try:
        object_name = urllib.parse.unquote(object_name)

        # Build visibility context
        user = session.get('user', {})
        role = user.get('role', 'guest') if user else 'guest'
        is_admin = user.get('is_admin', False) if user else False
        is_logged_in = bool(user)
        can_see_restricted = is_admin or role in ('user', 'admin')
        visibility = {
            'detect': can_see_restricted,
            'spectroscopy': can_see_restricted,
            'comments': can_see_restricted,
            'tags': can_see_restricted,
            'peak_abs_mag': can_see_restricted,
            'phot_controls': is_logged_in,
        }

        # Log view
        user_email = user.get('email') if user else None
        TNSObjectDB.log_object_view(object_name, user_email)
        
        # Update absolute magnitude and brightest mag
        update_object_abs_mag(object_name)
        
        # Try exact match first using direct SQL query
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        # Exact match queries (try multiple variants)
        tag_logic = """
        CASE o.status
            WHEN 'Finish'    THEN 'finished'
            WHEN 'Follow-up' THEN 'followup'
            WHEN 'Snoozed'   THEN 'snoozed'
            ELSE 'object'
        END as tag
        """
        
        exact_queries = [
            # Full name match (case insensitive)
            f"""SELECT o.obj_id AS objid, o.name_prefix, o.name, o.ra, o.dec AS declination,
                      o.redshift, NULL::int AS typeid, o.type,
                      NULL::int AS reporting_groupid, o.report_group AS reporting_group,
                      NULL::int AS source_groupid, o.source_group,
                      to_char(TIMESTAMP '1858-11-17' + o.discovery_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS discoverydate,
                      o.discovery_mag AS discoverymag, o.discovery_filter AS discmagfilter,
                      o.discovery_filter AS filter, array_to_string(o.reporters, ', ') AS reporters,
                      to_char(TIMESTAMP '1858-11-17' + o.received_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS time_received,
                      COALESCE(o.internal_name,'') AS internal_names, o.discovery_ADS AS discovery_ads_bibcode,
                      o.class_ADS AS class_ads_bibcodes,
                      to_char(TIMESTAMP '1858-11-17' + o.creation_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS creationdate,
                      to_char(TIMESTAMP '1858-11-17' + o.last_modified_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS lastmodified,
                      o.brightest_mag, o.brightest_abs_mag, array_to_string(o.tag, ', ') AS tags,
                      {tag_logic}
               FROM transient.objects o
               WHERE (COALESCE(o.name_prefix, '') || COALESCE(o.name, '')) ILIKE %s""",
            # Name only match (case insensitive)
            f"""SELECT o.obj_id AS objid, o.name_prefix, o.name, o.ra, o.dec AS declination,
                      o.redshift, NULL::int AS typeid, o.type,
                      NULL::int AS reporting_groupid, o.report_group AS reporting_group,
                      NULL::int AS source_groupid, o.source_group,
                      to_char(TIMESTAMP '1858-11-17' + o.discovery_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS discoverydate,
                      o.discovery_mag AS discoverymag, o.discovery_filter AS discmagfilter,
                      o.discovery_filter AS filter, array_to_string(o.reporters, ', ') AS reporters,
                      to_char(TIMESTAMP '1858-11-17' + o.received_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS time_received,
                      COALESCE(o.internal_name,'') AS internal_names, o.discovery_ADS AS discovery_ads_bibcode,
                      o.class_ADS AS class_ads_bibcodes,
                      to_char(TIMESTAMP '1858-11-17' + o.creation_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS creationdate,
                      to_char(TIMESTAMP '1858-11-17' + o.last_modified_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS lastmodified,
                      o.brightest_mag, o.brightest_abs_mag, array_to_string(o.tag, ', ') AS tags,
                      {tag_logic}
               FROM transient.objects o
               WHERE o.name ILIKE %s"""
        ]
        
        matching_obj = None
        for i, query in enumerate(exact_queries):
            cursor.execute(query, (object_name,))
            result = cursor.fetchone()
            if result:
                columns = [desc[0] for desc in cursor.description]
                matching_obj = dict(zip(columns, result))
                break

        # If exact match found but URL includes prefix, redirect to name-only canonical URL
        # e.g. /object/AT2025abc → /object/2025abc
        if matching_obj:
            prefix    = (matching_obj.get('name_prefix') or '').strip()
            name_only = (matching_obj.get('name') or '').strip()
            if prefix and object_name.lower() != name_only.lower():
                conn.close()
                return redirect(url_for('marshal_bp.object_detail_generic', object_name=name_only))

        # If still no match, try internal_names (e.g. ZTF ID) and tags (e.g. EP name)
        if not matching_obj:
            alias_query = """
                SELECT name_prefix, name
                FROM transient.objects
                WHERE internal_name ILIKE %s
                   OR EXISTS (
                       SELECT 1 FROM unnest(tag) t(v)
                       WHERE trim(t.v) ILIKE %s
                   )
                ORDER BY discovery_date DESC NULLS LAST
                LIMIT 1
            """
            cursor.execute(alias_query, (f'%{object_name}%', object_name))
            alias_result = cursor.fetchone()
            if alias_result:
                # Redirect to name-only (no prefix) canonical URL
                canonical = (alias_result[1] or '').strip()
                conn.close()
                return redirect(url_for('marshal_bp.object_detail_generic', object_name=canonical))

        # If still no match, strip AT/SN prefix and retry —
        # handles the AT→SN classification scenario:
        # e.g. /object/AT2025wny → object was classified, now name_prefix='SN' → find by name='2025wny'
        if not matching_obj:
            import re as _re
            prefix_stripped = _re.sub(
                r'^(?:AT|SN|SLSN-I{1,2}|Ia|II)\s*(?=[0-9]{4})',
                '', object_name, flags=_re.IGNORECASE
            )
            if prefix_stripped and prefix_stripped.lower() != object_name.lower():
                # Try name-only match with stripped value
                cursor.execute(
                    f"""SELECT o.obj_id AS objid, o.name_prefix, o.name, o.ra, o.dec AS declination,
                              o.redshift, NULL::int AS typeid, o.type,
                              NULL::int AS reporting_groupid, o.report_group AS reporting_group,
                              NULL::int AS source_groupid, o.source_group,
                              to_char(TIMESTAMP '1858-11-17' + o.discovery_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS discoverydate,
                              o.discovery_mag AS discoverymag, o.discovery_filter AS discmagfilter,
                              o.discovery_filter AS filter, array_to_string(o.reporters, ', ') AS reporters,
                              to_char(TIMESTAMP '1858-11-17' + o.received_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS time_received,
                              COALESCE(o.internal_name,'') AS internal_names, o.discovery_ADS AS discovery_ads_bibcode,
                              o.class_ADS AS class_ads_bibcodes,
                              to_char(TIMESTAMP '1858-11-17' + o.creation_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS creationdate,
                              to_char(TIMESTAMP '1858-11-17' + o.last_modified_date * INTERVAL '1 day', 'YYYY-MM-DD HH24:MI:SS') AS lastmodified,
                              o.brightest_mag, o.brightest_abs_mag, array_to_string(o.tag, ', ') AS tags,
                              CASE o.status
                                  WHEN 'Finish'    THEN 'finished'
                                  WHEN 'Follow-up' THEN 'followup'
                                  WHEN 'Snoozed'   THEN 'snoozed'
                                  ELSE 'object'
                              END as tag
                         FROM transient.objects o
                        WHERE o.name ILIKE %s""",
                    (prefix_stripped,)
                )
                result = cursor.fetchone()
                if result:
                    columns = [desc[0] for desc in cursor.description]
                    matching_obj = dict(zip(columns, result))
                    # Redirect to canonical name-only URL
                    canonical = (matching_obj.get('name') or prefix_stripped).strip()
                    conn.close()
                    return redirect(url_for('marshal_bp.object_detail_generic', object_name=canonical))

        conn.close()

        # If no exact match, fall back to fuzzy search
        if not matching_obj:
            results = search_tns_objects(search_term=object_name, limit=50)

            # Find exact match in fuzzy results
            for obj in results:
                full_name = (obj.get('name_prefix', '') + obj.get('name', '')).strip()
                name_only = obj.get('name', '').strip()

                if (full_name.lower() == object_name.lower() or
                        name_only.lower() == object_name.lower()):
                    matching_obj = obj
                    break
                    
        
        if not matching_obj:
            flash(f'Object {object_name} not found.', 'error')
            return redirect(url_for('marshal.marshal'))
        
        # Values are already calculated by update_object_abs_mag and fetched from DB
        # No need to recalculate here

        # Calculate distance if redshift is available
        if matching_obj and matching_obj.get('redshift') is not None:
            try:
                from app.services.astro.astronomy_calculator import calculate_redshift_distance
                z = float(matching_obj['redshift'])
                if z > 0:
                    dist_result = calculate_redshift_distance(z)
                    matching_obj['distance_mpc'] = dist_result.get('distance_mpc')
            except Exception as e:
                print(f"Error calculating distance: {e}")

        # Convert datetime objects to strings for template compatibility
        if matching_obj:
            for key, value in matching_obj.items():
                if isinstance(value, datetime):
                    matching_obj[key] = value.strftime('%Y-%m-%d %H:%M:%S')
        
        return render_template('object_detail.html', 
                             current_path='/object',
                             object_data=matching_obj,
                             object_name=object_name,
                             visibility=visibility)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash('Error loading object data.', 'error')
        return redirect(url_for('marshal.marshal'))

@objects_bp.route('/object/<int:year><string:letters>')
def object_detail_tns_format(year, letters):
    try:
        # Construct TNS-style name from year and letters
        object_name = f"{year}{letters}"

        # Build visibility context
        user = session.get('user', {})
        role = user.get('role', 'guest') if user else 'guest'
        is_admin = user.get('is_admin', False) if user else False
        is_logged_in = bool(user)
        can_see_restricted = is_admin or role in ('user', 'admin')
        visibility = {
            'detect': can_see_restricted,
            'spectroscopy': can_see_restricted,
            'comments': can_see_restricted,
            'tags': can_see_restricted,
            'peak_abs_mag': can_see_restricted,
            'phot_controls': is_logged_in,
        }

        # Log view
        user_email = user.get('email') if user else None
        TNSObjectDB.log_object_view(object_name, user_email)
        
        # Update absolute magnitude and brightest mag
        update_object_abs_mag(object_name)
        
        # Try exact match first using direct SQL query
        conn = get_tns_db_connection()
        cursor = conn.cursor()
        
        tag_logic = """
        CASE o.status
            WHEN 'Finish'    THEN 'finished'
            WHEN 'Follow-up' THEN 'followup'
            WHEN 'Snoozed'   THEN 'snoozed'
            ELSE 'object'
        END as tag
        """
        
        # Exact match query - match name exactly (case insensitive)
        exact_query = f"""SELECT {OBJECT_COMPAT_COLS}
               FROM transient.objects o
               WHERE o.name ILIKE %s"""
        
        cursor.execute(exact_query, (object_name,))
        result = cursor.fetchone()
        matching_obj = None
        
        if result:
            columns = [desc[0] for desc in cursor.description]
            matching_obj = dict(zip(columns, result))
        
        conn.close()
        
        # If no exact match, fall back to fuzzy search
        if not matching_obj:
            results = search_tns_objects(search_term=object_name, limit=50)
            
            # Find exact match based on year + letters pattern
            for obj in results:
                full_name = (obj.get('name_prefix', '') + obj.get('name', '')).strip()
                name_only = obj.get('name', '').strip()
                
                # Strategy 1: Direct match on name only
                if name_only.lower() == object_name.lower():
                    matching_obj = obj
                    break
                
                # Strategy 2: Direct match on full name
                if full_name.lower() == object_name.lower():
                    matching_obj = obj
                    break
                
                # Strategy 3: Extract year and letters from full name using regex
                match = re.search(r'(\d{4})([a-zA-Z]+)$', name_only)
                if match:
                    extracted_name = f"{match.group(1)}{match.group(2)}"
                    if extracted_name.lower() == object_name.lower():
                        matching_obj = obj
                        break
        
        if not matching_obj:
            flash(f'Object {object_name} not found.', 'error')
            return redirect(url_for('marshal.marshal'))
        
        # Values are already calculated by update_object_abs_mag and fetched from DB
        # No need to recalculate here

        # Calculate distance if redshift is available
        if matching_obj and matching_obj.get('redshift') is not None:
            try:
                from app.services.astro.astronomy_calculator import calculate_redshift_distance
                z = float(matching_obj['redshift'])
                if z > 0:
                    dist_result = calculate_redshift_distance(z)
                    matching_obj['distance_mpc'] = dist_result.get('distance_mpc')
            except Exception as e:
                print(f"Error calculating distance: {e}")

        # Convert datetime objects to strings for template compatibility
        if matching_obj:
            for key, value in matching_obj.items():
                if isinstance(value, datetime):
                    matching_obj[key] = value.strftime('%Y-%m-%d %H:%M:%S')
        
        return render_template('object_detail.html', 
                             current_path='/object',
                             object_data=matching_obj,
                             object_name=object_name,
                             visibility=visibility)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        flash('Error loading object data.', 'error')
        return redirect(url_for('marshal.marshal'))
