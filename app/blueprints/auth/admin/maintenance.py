"""Admin panel actions — maintenance (split from admin_routes.py)."""
from flask import jsonify
import os
from app.db.auth import check_data_consistency, clean_data_consistency
import logging
from app.core.auth import admin_required

logger = logging.getLogger(__name__)
from . import admin_bp


# ===============================================================================
# DATA CONSISTENCY MANAGEMENT
# ===============================================================================
@admin_bp.route('/admin/check-consistency')
@admin_required
def check_consistency():
    
    issues = check_data_consistency()

    return jsonify({
        'success': True,
        'issues': issues,
        'has_issues': issues.get('total_issues', len(issues.get('issues', []))) > 0
    })

@admin_bp.route('/admin/clean-consistency', methods=['POST'])
@admin_required
def clean_consistency():
    
    cleaned_count = clean_data_consistency()
    
    return jsonify({
        'success': True,
        'message': f'Cleaned {cleaned_count} data consistency issues',
        'cleaned_count': cleaned_count
    })

# ===============================================================================
# MANUAL BACKUP
# ===============================================================================
@admin_bp.route('/admin/backup-now', methods=['POST'])
@admin_required
def backup_now():
    try:
        from app.services.jobs.backup import run_daily_backup
        run_daily_backup(force=True)
        return jsonify({'success': True, 'message': 'Backup completed successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===============================================================================
# DOCUMENT RESOURCE MANAGEMENT
# ===============================================================================
@admin_bp.route('/admin/documents/clean-images', methods=['POST'])
@admin_required
def clean_unused_images():
        
    try:
        tutorials_dir = os.path.join(admin_bp.root_path, 'static', 'tutorials')
        images_dir = os.path.join(tutorials_dir, 'images')
        
        if not os.path.exists(images_dir):
            return jsonify({'success': True, 'message': 'No images directory found', 'cleaned_count': 0})
            
        # 1. Collect all images on disk
        all_images = set(os.listdir(images_dir))
        
        # 2. Extract referenced images from all markdown files
        used_images = set()
        for filename in os.listdir(tutorials_dir):
            if filename.endswith('.md'):
                filepath = os.path.join(tutorials_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Match formats like markdown image ![](images/xxx.png) or HTML <img src=".../images/xxx.png">
                    # But more simply, check if image name exists in text
                    for img in all_images:
                        if img in content:
                            used_images.add(img)
                            
        # 3. Determine unused images
        unused_images = all_images - used_images
        
        # 4. Remove unused images
        cleaned_count = 0
        for img in unused_images:
            try:
                os.remove(os.path.join(images_dir, img))
                cleaned_count += 1
            except Exception as e:
                logger.error('Error removing image %s: %s', img, e)
                
        return jsonify({
            'success': True,
            'message': f'Cleaned {cleaned_count} unused image(s)',
            'cleaned_count': cleaned_count
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===============================================================================
# PHOTOMETRY SCHEDULER
# ===============================================================================
@admin_bp.route('/admin/run-photometry-fetch', methods=['POST'])
@admin_required
def run_photometry_fetch():

    from app.services.photometry.phot_scheduler import fetch_inbox_photometry, is_running
    import threading

    if is_running():
        return jsonify({'success': False, 'message': 'Photometry fetch is already running'}), 409

    def _run():
        fetch_inbox_photometry()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': 'Photometry fetch started in background'})

@admin_bp.route('/admin/photometry-fetch-status')
@admin_required
def photometry_fetch_status():

    from app.services.photometry.phot_scheduler import is_running, get_progress
    progress = get_progress()
    return jsonify({'running': is_running(), **progress})

@admin_bp.route('/admin/run-missing-phot-fetch', methods=['POST'])
@admin_required
def run_missing_phot_fetch():

    from app.services.photometry.phot_scheduler import fetch_missing_photometry, is_missing_running
    import threading

    if is_missing_running():
        return jsonify({'success': False, 'message': 'Missing phot check is already running'}), 409

    def _run():
        fetch_missing_photometry()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': 'Missing photometry check started in background'})

@admin_bp.route('/admin/run-update-target-mags', methods=['POST'])
@admin_required
def run_update_target_mags():

    from app.services.photometry.phot_scheduler import update_target_mags
    import threading

    def _run():
        update_target_mags()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': 'Target magnitude update started in background'})
