import os
import sys

# Add parent directory to path to import download_phot
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(parent_dir)

try:
    from download_phot import process_single_object_workflow, get_photometry, upload_photometry_to_db
except ImportError:
    # Fallback if running from different location
    sys.path.append(os.path.join(parent_dir, 'modules'))
    from download_phot import process_single_object_workflow, get_photometry, upload_photometry_to_db

def get_photometry_wrapper(object_name, ra=None, dec=None):
    print(f"Getting photometry for {object_name} using download_phot module...")

    process_single_object_workflow(object_name)

if __name__ == "__main__":
    # Example usage
    target_name = "2025zmn"
    get_photometry_wrapper(target_name)
