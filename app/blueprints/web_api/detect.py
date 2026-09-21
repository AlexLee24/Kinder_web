"""JSON API used by the marshal/object pages and external API-key clients — detect (split from web_api_routes.py)."""
import urllib.parse
from flask import request, jsonify
from app.db import get_db_connection
import logging

logger = logging.getLogger(__name__)
from . import web_api_bp


@web_api_bp.route('/api/object/<object_name>/detect_cross_match', methods=['GET'])
def trigger_detect_cross_match(object_name):
    """DETECT for one object: DB-first, run (the embedded pipeline) on ``force=true``
    or when it has never run. The response carries the candidate rows and DETECT's
    verdict (transient.detect_screen)."""
    try:
        from app.services.detect.detect_cross_match import has_detect_run, get_detect_results_for_target, get_detect_screen_for_target
        from app.services.detect import detect_pipeline
        from app.db.transient import get_detect_images as _get_imgs
        import re as _re
        object_name = urllib.parse.unquote(object_name).strip()
        # Normalize: strip AT/SN prefix (allow optional spaces, case-insensitive)
        _m = _re.match(r'^(?:AT|SN)\s*(\d.+)$', object_name, flags=_re.IGNORECASE)
        if _m:
            object_name = _m.group(1)

        # Resolve canonical object name from DB (case-insensitive) for stable downstream queries.
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT obj_id, name, ra, dec FROM transient.objects "
                    "WHERE lower(name) = lower(%s) LIMIT 1",
                    (object_name,)
                )
                row = cur.fetchone()

        if not row:
            return jsonify({'success': False, 'error': 'Object not found in database'}), 404

        obj_id, canonical_name, ra, dec = row
        object_name = canonical_name

        force = (request.args.get('force') or '').strip().lower() == 'true'
        screen = get_detect_screen_for_target(object_name)

        # ── DB-first: DETECT (daemon or the hourly import) has already been here ──
        if not force and (has_detect_run(object_name) or screen):
            results = get_detect_results_for_target(object_name)
            imgs = _get_imgs(canonical_name)
            return jsonify({'success': True, 'ran_now': False, 'results': results, 'screen': screen,
                            'detect_image_id': imgs[0]['image_id'] if imgs else None})

        # ── Run path: the same pipeline as the daemon (cross-match, rule v1, screening, finder) ──
        if not detect_pipeline.ENABLED:
            return jsonify({'success': False, 'error': 'DETECT is not enabled in this web instance (DETECT_IN_WEB=0)'}), 503
        detect_pipeline.run_single(object_name)
        try:
            from app.blueprints.detect.cache import _soft_invalidate_page_cache
            _soft_invalidate_page_cache()
        except Exception:
            pass

        final_results = get_detect_results_for_target(object_name)
        imgs = _get_imgs(canonical_name)
        return jsonify({'success': True, 'ran_now': True, 'results': final_results,
                        'screen': get_detect_screen_for_target(object_name),
                        'detect_image_id': imgs[0]['image_id'] if imgs else None})

    except Exception as e:
        logger.error(f'Error running detect for {object_name}: {str(e)}')
        return jsonify({'success': False, 'error': str(e)}), 500

@web_api_bp.route('/api/object/<object_name>/detect_images', methods=['GET'])
def list_detect_images(object_name):
    """Return list of DETECT finder-chart image metadata for the object."""
    try:
        from app.db.transient import get_detect_images
        name = urllib.parse.unquote(object_name).strip()
        images = get_detect_images(name)
        return jsonify({'success': True, 'images': images})
    except Exception as e:
        logger.error('list_detect_images %s: %s', object_name, e)
        return jsonify({'success': False, 'error': str(e)}), 500

@web_api_bp.route('/api/object/<object_name>/detect_images/generate', methods=['POST'])
def generate_detect_images(object_name):
    """(Re)generate the DETECT finder: the pipeline draws the LS DR10 cutout with the
    host ellipse itself, so this is a re-run of DETECT for the object."""
    try:
        from app.services.detect import detect_pipeline
        from app.db.transient import get_detect_images

        name = urllib.parse.unquote(object_name).strip()
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT obj_id, name FROM transient.objects WHERE lower(name) = lower(%s) LIMIT 1",
                    (name,)
                )
                row = cur.fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Object not found'}), 404
        canonical_name = row[1]
        if not detect_pipeline.ENABLED:
            return jsonify({'success': False, 'error': 'DETECT is not enabled in this web instance (DETECT_IN_WEB=0)'}), 503
        detect_pipeline.run_single(canonical_name)
        images = get_detect_images(canonical_name)
        return jsonify({'success': True, 'images': images,
                        'detect_image_id': images[0]['image_id'] if images else None})

    except Exception as e:
        logger.error('generate_detect_images %s: %s', object_name, e)
        return jsonify({'success': False, 'error': str(e)}), 500
