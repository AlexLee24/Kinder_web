import os
import sys
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from astropy.coordinates import SkyCoord
import astropy.units as u

# Add parent directory to path to import postgres_database
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(parent_dir)

try:
    from postgres_database import get_db_connection
except ImportError:
    # Fallback if running from different location
    sys.path.append(os.path.join(parent_dir, 'modules'))
    from postgres_database import get_db_connection

def lens_cross_match_hsu(ra, dec, target_name, search_radius=15):
    """
    Cross match with Lens Hsu data in PostgreSQL.
    """
    return _generic_lens_cross_match(ra, dec, target_name, 'lens_hsu', 'Lens_Hsu', search_radius)

def lens_cross_match_karp(ra, dec, target_name, search_radius=15):
    """
    Cross match with Lens Karp data in PostgreSQL.
    """
    return _generic_lens_cross_match(ra, dec, target_name, 'lens_karp', 'Lens_Karp', search_radius)

def _generic_lens_cross_match(ra, dec, target_name, table_name, catalog_label, search_radius):
    search_radius_deg = search_radius / 3600.0
    
    # Bounding box
    ra_min = ra - search_radius_deg
    ra_max = ra + search_radius_deg
    dec_min = dec - search_radius_deg
    dec_max = dec + search_radius_deg
    
    matched_data = []
    
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Select candidates within bounding box
                # Assuming columns are 'ra' and 'dec' based on schema check
                query = f"""
                    SELECT * FROM {table_name} 
                    WHERE ra BETWEEN %s AND %s 
                    AND dec BETWEEN %s AND %s
                """
                cur.execute(query, (ra_min, ra_max, dec_min, dec_max))
                candidates = cur.fetchall()
                
                target_coord = SkyCoord(ra=ra*u.degree, dec=dec*u.degree, frame='icrs')
                
                for row in candidates:
                    # Calculate exact separation
                    source_coord = SkyCoord(
                        ra=row['ra']*u.degree, 
                        dec=row['dec']*u.degree, 
                        frame='icrs'
                    )
                    separation = target_coord.separation(source_coord).arcsec
                    
                    if separation <= search_radius:
                        row_dict = dict(row)
                        row_dict['separation_arcsec'] = separation
                        matched_data.append(row_dict)
                        
                        # DB insertion moved to _daily_run.py to handle is_Host logic
            
            # No commit needed as we are only reading
            
    except Exception as e:
        print(f"Error in Lens cross match ({catalog_label}): {e}")
        
    return matched_data

if __name__ == "__main__":
    # Example usage
    ra_example, dec_example = 128.9593, 40.731
    target_name_example = "TEST_LENS_OBJECT"
    
    results_karp = lens_cross_match_karp(ra_example, dec_example, target_name_example, search_radius=15)
    
    print(f"Found {len(results_karp)} matches in Karp within 15 arcseconds:")
    for match in results_karp:
        print(match)
