import os
import json
import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astroquery.vizier import Vizier
from psycopg2.extras import RealDictCursor
# from modules.postgres_database import get_db_connection
from postgres_database import get_db_connection


class _NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)

LENS_CATALOGS = {
    "HOLISMOKES_II": "J/A+A/644/A163",
    "HOLISMOKES_VI": "J/A+A/653/L6",
    "HOLISMOKES_VIII": "J/A+A/662/A4",
    "SLACS_IV": "J/ApJ/682/964",
    "SLACS_XI": "J/ApJ/777/101",
    "BELLS": "J/ApJ/744/41",
    "Gaia_GraL_I": "J/A+A/622/A165",
    "DES_SV": "J/ApJ/817/60",
    "CASTLES": "VII/229"
}

def desi_cross_match_single(ra, dec, search_radius=30):
    search_radius_deg = search_radius / 3600.0
    matched_data = []
    
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                ra_min = ra - search_radius_deg
                ra_max = ra + search_radius_deg
                dec_min = dec - search_radius_deg
                dec_max = dec + search_radius_deg
            
                query = """
                    SELECT * FROM desi_data 
                    WHERE ra BETWEEN %s AND %s 
                    AND dec BETWEEN %s AND %s
                """
                cur.execute(query, (ra_min, ra_max, dec_min, dec_max))
                candidates = cur.fetchall()
                
                target_coord = SkyCoord(ra=ra*u.degree, dec=dec*u.degree, frame='icrs')
                
                for row in candidates:
                    source_coord = SkyCoord(ra=row['ra']*u.degree, dec=row['dec']*u.degree, frame='icrs')
                    separation = target_coord.separation(source_coord).arcsec
                    
                    if separation <= search_radius:
                        row_dict = dict(row)
                        row_dict['separation_arcsec'] = float(separation)
                        matched_data.append(row_dict)
    except Exception as e:
        print(f"Error in DESI cross match: {e}")
        
    return matched_data

def lens_cross_match_catalogue_single(ra, dec, search_radius=10, table_name='lens_catalogue', catalog_label='Lens_Catalogue'):
    search_radius_deg = search_radius / 3600.0
    matched_data = []
    
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                ra_min = ra - search_radius_deg
                ra_max = ra + search_radius_deg
                dec_min = dec - search_radius_deg
                dec_max = dec + search_radius_deg
                
                query = f"""
                    SELECT * FROM {table_name} 
                    WHERE ra BETWEEN %s AND %s 
                    AND dec BETWEEN %s AND %s
                """
                cur.execute(query, (ra_min, ra_max, dec_min, dec_max))
                candidates = cur.fetchall()
                
                target_coord = SkyCoord(ra=ra*u.degree, dec=dec*u.degree, frame='icrs')
                
                for row in candidates:
                    source_coord = SkyCoord(ra=row['ra']*u.degree, dec=row['dec']*u.degree, frame='icrs')
                    separation = target_coord.separation(source_coord).arcsec
                    
                    if separation <= search_radius:
                        row_dict = dict(row)
                        row_dict['separation_arcsec'] = float(separation)
                        matched_data.append(row_dict)
    except Exception as e:
        print(f"Error in Lens cross match ({catalog_label}): {e}")
        
    return matched_data

def comprehensive_lens_match_single(ra, dec, search_radius=10):
    matched_data = []
    v = Vizier(columns=["**", "_r"])
    v.ROW_LIMIT = -1
    
    target_coord = SkyCoord(ra=ra*u.degree, dec=dec*u.degree, frame='icrs')
    
    for cat_name, cat_id in LENS_CATALOGS.items():
        try:
            result = v.query_region(target_coord, radius=search_radius*u.arcsec, catalog=cat_id)
            if len(result) > 0:
                table = result[0]
                for row in table:
                    sep = None
                    if '_r' in table.colnames and row['_r'] is not None:
                        try:
                            _r_unit = table['_r'].unit
                            _r_val = float(row['_r'])
                            if _r_unit is not None:
                                sep = float((_r_val * _r_unit).to(u.arcsec).value)
                            else:
                                # Vizier default is arcminutes
                                sep = _r_val * 60.0
                        except Exception:
                            # Fallback: assume arcminutes (Vizier default)
                            sep = float(row['_r']) * 60.0
                    
                    if sep is not None and sep > search_radius:
                        continue
                        
                    row_dict = {
                        'origin_catalog_name': cat_name,
                        'origin_catalog_id': cat_id
                    }
                    
                    for col in table.colnames:
                        if col == '_r':
                            continue
                        val = row[col]
                        if hasattr(val, 'mask') and val.mask:
                            row_dict[col] = None
                        elif isinstance(val, np.integer):
                            row_dict[col] = int(val)
                        elif isinstance(val, np.floating):
                            row_dict[col] = float(val)
                        elif isinstance(val, np.bool_):
                            row_dict[col] = bool(val)
                        elif isinstance(val, (int, float, str, bool, type(None))):
                            row_dict[col] = val
                        else:
                            row_dict[col] = str(val)
                    
                    if sep is not None:
                        row_dict['separation_arcsec'] = sep
                        if sep < 3.0:
                            row_dict['priority_tag'] = "HIGH_PRIORITY_GLSN_CANDIDATE"
                        else:
                            row_dict['priority_tag'] = "POTENTIAL_LENS_ENVIRONMENT"

                    matched_data.append(row_dict)
        except Exception as e:
            continue
            
    return matched_data

def run_all_detect(target_name, ra, dec):
    """Run all cross-matches for the target and store results."""
    # Run algorithms
    desi = desi_cross_match_single(ra, dec, search_radius=30)
    
    # Try all LENS
    lens_hsu = lens_cross_match_catalogue_single(ra, dec, search_radius=10, table_name='lens_hsu', catalog_label='Lens_Hsu')
    lens_karp = lens_cross_match_catalogue_single(ra, dec, search_radius=10, table_name='lens_karp', catalog_label='Lens_Karp')
    lens_cat = lens_cross_match_catalogue_single(ra, dec, search_radius=10, table_name='lens_catalogue', catalog_label='Lens_Catalogue')
    
    lens_online = comprehensive_lens_match_single(ra, dec, search_radius=10)
    
    results = []
    
    def _add_to_results(matches, catalog_name):
        for m in matches:
            sep = float(m.get('separation_arcsec', 0.0))
            results.append({
                'target_name': target_name,
                'catalog_name': catalog_name,
                'match_data': json.dumps({k: v for k, v in m.items() if k != 'separation_arcsec'}, cls=_NumpyEncoder),
                'separation_arcsec': sep
            })

    _add_to_results(desi, 'DESI')
    _add_to_results(lens_hsu, 'LENS_HSU')
    _add_to_results(lens_karp, 'LENS_KARP')
    _add_to_results(lens_cat, 'LENS_CATALOGUE')
    
    # For online lens, it has its own origin_catalog_name
    for m in lens_online:
        cat_name = m.get('origin_catalog_name', 'ONLINE_LENS')
        sep = float(m.get('separation_arcsec', 0.0))
        results.append({
            'target_name': target_name,
            'catalog_name': cat_name,
            'match_data': json.dumps({k: v for k, v in m.items() if k != 'separation_arcsec'}, cls=_NumpyEncoder),
            'separation_arcsec': sep
        })
        
    return results

def has_detect_run(target_name):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Check for the special status row which indicates a run occurred
                cur.execute("SELECT 1 FROM detect_cross_match_results WHERE target_name = %s AND catalog_name = 'DETECT_STATUS_RUN' LIMIT 1", (target_name,))
                return cur.fetchone() is not None
    except Exception as e:
        print(f"Error checking detect run status: {e}")
        return False

def save_detect_results(target_name, results):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Insert actual matches
                if results:
                    for r in results:
                        cur.execute("""
                            INSERT INTO detect_cross_match_results 
                            (target_name, catalog_name, match_data, separation_arcsec)
                            VALUES (%s, %s, %s, %s)
                        """, (
                            r['target_name'],
                            r['catalog_name'],
                            r['match_data'],
                            float(r['separation_arcsec']) if r['separation_arcsec'] is not None else None
                        ))
                
                # Insert the special status row indicating we've run it
                cur.execute("""
                    INSERT INTO detect_cross_match_results 
                    (target_name, catalog_name, match_data, separation_arcsec)
                    VALUES (%s, %s, %s, %s)
                """, (target_name, 'DETECT_STATUS_RUN', '{}', 0.0))
                
                conn.commit()
    except Exception as e:
        print(f"Error saving detect results: {e}")

def get_detect_results_for_target(target_name):
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT catalog_name, match_data, separation_arcsec, created_at, is_host, flag 
                    FROM detect_cross_match_results 
                    WHERE target_name = %s AND catalog_name != 'DETECT_STATUS_RUN'
                    ORDER BY separation_arcsec ASC
                """, (target_name,))
                
                rows = cur.fetchall()
                results = []
                for row in rows:
                    r_dict = dict(row)
                    if r_dict.get('created_at'):
                        r_dict['created_at'] = r_dict['created_at'].isoformat()
                    results.append(r_dict)
                return results
    except Exception as e:
        print(f"Error getting detect results: {e}")
        return []


if __name__ == '__main__':
    # Test target: SN 2024ypp (or change to any known object)
    TEST_NAME = "TEST"
    # TEST_RA   = 336.537500   # degrees
    # TEST_DEC  = 0.695000    # degrees
    TEST_RA   = 109.143750    # degrees (example: RA of a known lens)
    TEST_DEC  = 38.352253     # degrees (example: Dec of a

    print("=" * 60)
    print(f"Testing cross-match for: {TEST_NAME}")
    print(f"  RA={TEST_RA:.5f} deg,  Dec={TEST_DEC:.5f} deg")
    print("=" * 60)

    # ── 1. DESI local DB (r < 30") ─────────────────────────────
    print("\n[1] DESI cross-match (r < 30\")")
    desi_matches = desi_cross_match_single(TEST_RA, TEST_DEC, search_radius=30)
    if desi_matches:
        for m in desi_matches:
            print(f"  sep={m['separation_arcsec']:.2f}\"  z_spec={m.get('z_spec', m.get('Z_SPEC', 'N/A'))}  type={m.get('spectype', m.get('type', 'N/A'))}")
    else:
        print("  No matches found.")

    # ── 2. Local Lens DBs (r < 10") ────────────────────────────
    for tbl, label in [('lens_hsu', 'LENS_HSU'), ('lens_karp', 'LENS_KARP'), ('lens_catalogue', 'LENS_CATALOGUE')]:
        print(f"\n[2] {label} cross-match (r < 10\")")
        matches = lens_cross_match_catalogue_single(TEST_RA, TEST_DEC, search_radius=10, table_name=tbl, catalog_label=label)
        if matches:
            for m in matches:
                sep  = m['separation_arcsec']
                zl   = m.get('z_lens', 'N/A')
                zs   = m.get('z_source', m.get('z', 'N/A'))
                prob = m.get('lens_probability', 'N/A')
                grade = m.get('grade', 'N/A')
                print(f"  sep={sep:.2f}\"  z_lens={zl}  z_source={zs}  prob={prob}  grade={grade}")
        else:
            print("  No matches found.")

    # ── 3. Vizier online Lens catalogs (r < 10") ───────────────
    print("\n[3] Vizier online Lens catalogs (r < 10\")")
    online_matches = comprehensive_lens_match_single(TEST_RA, TEST_DEC, search_radius=10)
    if online_matches:
        for m in online_matches:
            cat  = m.get('origin_catalog_name', '?')
            sep  = m.get('separation_arcsec', '?')
            tag  = m.get('priority_tag', '')
            print(f"  [{cat}]  sep={sep:.2f}\"  tag={tag}")
            # Print all non-metadata keys
            skip = {'origin_catalog_name', 'origin_catalog_id', 'separation_arcsec', 'priority_tag'}
            extras = {k: v for k, v in m.items() if k not in skip and v is not None}
            if extras:
                print(f"    data: {extras}")
    else:
        print("  No matches found.")

    # ── 4. JSON serialisation sanity check ─────────────────────
    print("\n[4] JSON serialisation check")
    all_results = run_all_detect(TEST_NAME, TEST_RA, TEST_DEC)
    print(f"  Total result rows: {len(all_results)}")
    for r in all_results:
        try:
            parsed = json.loads(r['match_data'])
            print(f"  OK  catalog={r['catalog_name']}  sep={r['separation_arcsec']:.2f}\"  keys={list(parsed.keys())[:5]}")
        except Exception as e:
            print(f"  FAIL  catalog={r['catalog_name']}  error={e}")
            print(f"    raw match_data={r['match_data'][:200]}")

    print("\nDone.")

