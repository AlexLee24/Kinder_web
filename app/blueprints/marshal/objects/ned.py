"""Object detail page and per-object data APIs (blueprint name 'marshal_bp') — ned (split from object_routes.py)."""
import re
from flask import session, request, jsonify
import requests as _requests
from app.db import get_tns_db_connection
from app.core.request_validation import get_float_arg, ParamOutOfRangeError
from app.db.catalog import get_ned_cache, upsert_ned_cache
import logging

logger = logging.getLogger(__name__)
from . import objects_bp


# ============================================================
# NED Cone Search Proxy
# ============================================================
def _get_current_ned_host_name(target_name: str) -> str | None:
    """Return current NED host name for target from transient.objects.host_name."""
    if not target_name:
        return None
    try:
        conn = get_tns_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT host_name FROM transient.objects "
            "WHERE name = %s OR (COALESCE(name_prefix,'') || name) = %s LIMIT 1",
            (target_name, target_name)
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row and row[0] else None
    except Exception as e:
        logger.warning("[NED] read current host failed for %s: %s", target_name, e)
        return None

@objects_bp.route('/api/ned/cone')
def ned_cone_search():
    """Proxy NED cone search to avoid CORS.
    Query params: ra, dec, radius_arcsec (default 60), object_name, force (0/1)
    """
    try:
        ra     = get_float_arg('ra', 0)
        dec    = get_float_arg('dec', 0)
        radius = get_float_arg('radius_arcsec', 60)
        object_name = request.args.get('object_name', '').strip()
        force       = request.args.get('force', '0').strip() not in ('0', 'false', '')
        current_host = _get_current_ned_host_name(object_name) if object_name else None

        logger.info(
            "[NED] cone search start ra=%.6f dec=%.6f radius_arcsec=%.1f",
            ra, dec, radius
        )

        # --- Try DB cache first (unless force=true) ---
        if not force and object_name:
            cached = get_ned_cache(object_name, radius)
            if cached is not None:
                logger.info("[NED] cache hit for %s r=%.1f count=%d",
                            object_name, radius, cached['result_count'])
                return jsonify({
                    'success': True,
                    'count': cached['result_count'],
                    'results': cached['results'],
                    'from_cache': True,
                    'searched_at': cached.get('searched_at'),
                    'current_host': current_host,
                })

        radius_arcmin = radius / 60.0
        url = (
            "https://ned.ipac.caltech.edu/cgi-bin/objsearch"
            f"?lon={ra}d&lat={dec}d"
            f"&radius={radius_arcmin:.4f}"
            "&search_type=Near+Position+Search"
            "&in_csys=Equatorial&in_equinox=J2000.0"
            "&out_csys=Equatorial&out_equinox=J2000.0"
            "&obj_sort=Distance+to+search+center"
            "&of=ascii_bar&zv_breaker=30000.0&list_limit=500&img_stamp=NO"
            "&z_constraint=Unconstrained&nmp_op=ANY"
        )
        resp = _requests.get(url, timeout=60, headers={'User-Agent': 'KinderWeb/1.0'})
        logger.info("[NED] upstream status=%s", resp.status_code)
        resp.raise_for_status()

        def _norm(s):
            return ''.join(ch for ch in (s or '').lower() if ch.isalnum())

        def _first_float(s):
            if s is None:
                return None
            m = re.search(r'[-+]?\d+(?:\.\d+)?', str(s))
            return float(m.group(0)) if m else None

        def _parse_ra_deg(s):
            if s is None:
                return None
            raw = str(s).strip()
            if not raw:
                return None
            v = _first_float(raw)
            # Decimal degrees from NED are usually in [0, 360].
            if v is not None and 0.0 <= v <= 360.0 and len(raw.split()) == 1 and ':' not in raw:
                return v
            toks = [t for t in re.split(r'[:\s]+', raw) if t]
            if len(toks) >= 3:
                try:
                    h = float(toks[0]); m = float(toks[1]); sec = float(toks[2])
                    return (h + m / 60.0 + sec / 3600.0) * 15.0
                except ValueError:
                    return None
            return v

        def _parse_dec_deg(s):
            if s is None:
                return None
            raw = str(s).strip()
            if not raw:
                return None
            v = _first_float(raw)
            if v is not None and -90.0 <= v <= 90.0 and len(raw.split()) == 1 and ':' not in raw:
                return v
            toks = [t for t in re.split(r'[:\s]+', raw.replace('+', ' +').replace('-', ' -')) if t]
            if len(toks) >= 3:
                try:
                    d = float(toks[0]); m = float(toks[1]); sec = float(toks[2])
                    sign = -1.0 if d < 0 else 1.0
                    return sign * (abs(d) + m / 60.0 + sec / 3600.0)
                except ValueError:
                    return None
            return v

        lines = [ln.rstrip('\n') for ln in resp.text.splitlines()]
        header = None
        for ln in lines:
            if '|' not in ln:
                continue
            cols = [c.strip() for c in ln.split('|')]
            keyline = ' '.join(cols).lower()
            if ('object' in keyline and 'name' in keyline and 'ra' in keyline and 'dec' in keyline):
                header = cols
                break

        # Fallback to legacy index if header cannot be detected
        if not header:
            header = ['No.', 'Object Name', 'RA', 'DEC', 'Type', 'Velocity', 'Redshift', 'z flag', 'Magnitude']

        idx = {}
        for i, col in enumerate(header):
            n = _norm(col)
            if n in ('no', 'number', 'sep', 'separation') and 'distance' not in idx:
                idx['distance'] = i
            if ('object' in n and 'name' in n) or n in ('objname', 'name'):
                idx['objname'] = i
            if n.startswith('ra') and 'ra' not in idx:
                idx['ra'] = i
            if n.startswith('dec') and 'dec' not in idx:
                idx['dec'] = i
            if n in ('type', 'objtype', 'objecttype') and 'type' not in idx:
                idx['type'] = i
            if ('redshift' in n and 'flag' not in n) or n in ('z',):
                if 'redshift' not in idx:
                    idx['redshift'] = i
            if ('redshift' in n and 'flag' in n) or n in ('zflag', 'redshiftflag'):
                idx['redshift_type'] = i

        def _get(cols, key):
            i = idx.get(key)
            if i is None or i >= len(cols):
                return ''
            return cols[i].strip()

        results = []
        for ln in lines:
            line = ln.strip()
            if not line or '|' not in line:
                continue
            if line.startswith('#'):
                continue
            cols = [c.strip() for c in ln.split('|')]
            joined = ' '.join(cols).lower()
            if 'object name' in joined and 'ra' in joined and 'dec' in joined:
                continue
            if all((not c or set(c) <= set('-=')) for c in cols):
                continue

            objname = _get(cols, 'objname')
            if not objname:
                continue

            ra_val = _parse_ra_deg(_get(cols, 'ra'))
            dec_val = _parse_dec_deg(_get(cols, 'dec'))
            if ra_val is None or dec_val is None:
                continue

            obj = {
                'objname': objname,
                'ra': ra_val,
                'dec': dec_val,
                'type': _get(cols, 'type') or '',
                'redshift': _first_float(_get(cols, 'redshift')),
                'redshift_type': _get(cols, 'redshift_type') or '',
                'distance_arcmin': _first_float(_get(cols, 'distance')),
            }
            results.append(obj)

        sample = [
            {
                'name': r.get('objname', ''),
                'ra': r.get('ra'),
                'dec': r.get('dec'),
                'z': r.get('redshift'),
                'z_flag': r.get('redshift_type', ''),
            }
            for r in results[:3]
        ]
        logger.info(
            "[NED] parsed count=%d sample=%s",
            len(results),
            sample
        )

        # --- Write to DB cache ---
        if object_name:
            try:
                upsert_ned_cache(object_name, ra, dec, radius, results)
                logger.info("[NED] cached %d results for %s r=%.1f",
                            len(results), object_name, radius)
            except Exception as _ce:
                logger.warning("[NED] cache write failed: %s", _ce)

        return jsonify({'success': True, 'count': len(results), 'results': results,
                'from_cache': False, 'current_host': current_host})

    except _requests.Timeout as e:
        logger.warning("[NED] upstream timed out: %s", e)
        return jsonify({'success': False, 'error': f'NED request timed out: {e}'}), 502
    except _requests.RequestException as e:
        logger.error("[NED] upstream request failed: %s", e)
        return jsonify({'success': False, 'error': f'NED request failed: {e}'}), 502
    except ParamOutOfRangeError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.exception("[NED] cone search error")
        return jsonify({'success': False, 'error': str(e)}), 500

@objects_bp.route('/api/ned/set_host', methods=['POST'])
def ned_set_host():
    """Set selected NED object as host for the epessto support session.

    Host info is stored in the session only (via updateTargetState on the client).
    Redshift is returned whenever available so the client can fill it in.
    """
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        data = request.get_json(silent=True) or {}
        target_name = str(data.get('target_name') or '').strip()
        host_name   = str(data.get('host_name')   or '').strip()
        z_flag      = str(data.get('redshift_type') or '').strip()
        redshift_raw = data.get('redshift')

        if not target_name or not host_name:
            return jsonify({'success': False, 'error': 'Missing target_name or host_name'}), 400

        redshift_val = None
        if redshift_raw not in (None, ''):
            try:
                redshift_val = float(redshift_raw)
            except (ValueError, TypeError):
                redshift_val = None

        has_redshift = redshift_val is not None
        logger.info("[NED] set_host target=%s host=%s redshift=%s z_flag=%s",
                    target_name, host_name, redshift_val, z_flag or '-')

        return jsonify({
            'success': True,
            'host_name': host_name,
            'updated_redshift': has_redshift,
            'redshift': redshift_val,
            'z_flag': z_flag,
        })

    except Exception as e:
        logger.exception("[NED] set_host error")
        return jsonify({'success': False, 'error': str(e)}), 500

@objects_bp.route('/api/ned/unset_host', methods=['POST'])
def ned_unset_host():
    """Unset NED host for the epessto support session."""
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    if session['user'].get('role', 'guest') == 'guest' and not session['user'].get('is_admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        data = request.get_json(silent=True) or {}
        target_name = str(data.get('target_name') or '').strip()
        if not target_name:
            return jsonify({'success': False, 'error': 'Missing target_name'}), 400

        logger.info("[NED] unset_host target=%s", target_name)
        return jsonify({'success': True})

    except Exception as e:
        logger.exception("[NED] unset_host error")
        return jsonify({'success': False, 'error': str(e)}), 500
