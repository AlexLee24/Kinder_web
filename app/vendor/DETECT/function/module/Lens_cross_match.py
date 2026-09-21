import numpy as np
from function.database import CatalogueService


def _convert_numpy_types(obj):
    """Convert numpy types to Python native types for JSON serialization."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, bytes):
        return obj.decode('utf-8')
    else:
        return obj


def _extract_targets_from_dataset(dataset) -> list[tuple]:
    """Extract targets from dataset dict or return as-is if already a list."""
    if isinstance(dataset, dict):
        if 'targets' in dataset:
            return dataset['targets']
        elif 'followup' in dataset and dataset['followup'] and 'targets' in dataset['followup']:
            return dataset['followup']['targets']
        elif 'tns' in dataset and dataset['tns'] and 'targets' in dataset['tns']:
            return dataset['tns']['targets']
    elif isinstance(dataset, list):
        return dataset
    return []


def lens_cross_match(target_list, search_radius=15):
    """
    Cross-match with Lens data in PostgreSQL.

    Args:
        target_list (list | dict): List of tuples (ra, dec, target_name) or dataset dict
        search_radius (float): Search radius in arcseconds

    Returns:
        dict: Dictionary mapping target_name to list of matched dictionaries
    """
    targets = _extract_targets_from_dataset(target_list)
    if not targets:
        print("[WARNING] No targets provided for Lens cross-match")
        return {}

    try:
        return CatalogueService.cross_match_catalog(
            target_list=targets,
            catalog_name="Lens",
            search_radius=search_radius,
        )
    except (ValueError, KeyError) as e:
        print(f"[ERROR] Lens cross match failed: {type(e).__name__} - {e}")
        return {}
    except Exception as e:
        print(f"[ERROR] Unexpected error in Lens cross match: {type(e).__name__} - {e}")
        return {}

from astropy.coordinates import SkyCoord
import astropy.units as u
from astroquery.vizier import Vizier
from tqdm import tqdm

LENS_CATALOGS = {
    # ==========================================
    # HOLISMOKES
    # ==========================================
    "HOLISMOKES_II": "J/A+A/644/A163",
    "HOLISMOKES_VI": "J/A+A/653/L6",
    "HOLISMOKES_VIII": "J/A+A/662/A4",

    # ==========================================
    # SLACS (from SDSS cat)
    # ==========================================
    "SLACS_IV": "J/ApJ/682/964",
    "SLACS_XI": "J/ApJ/777/101",

    # ==========================================
    # SuGOHI (from Subaru)
    # ==========================================
    "SuGOHI_I": "J/PASJ/70/S29",
    "SuGOHI_II": "J/ApJ/867/107",

    # ==========================================
    # Other
    # ==========================================
    "BELLS": "J/ApJ/744/41",  # BOSS
    "Gaia_GraL_I": "J/A+A/622/A165",  # Gaia
    "DES_SV": "J/ApJ/817/60",  # DES
    "CASTLES": "VII/229"  # HST
}


def lens_cross_match_online(target_list, search_radius=10):
    """
    Cross-match targets against multiple public gravitational lens catalogs.

    Args:
        target_list (list): List of tuples (ra, dec, target_name)
        search_radius (float): Search radius in arcseconds, default is 10

    Returns:
        dict: Dictionary mapping target_name to list of matched dictionaries
    """
    catalogs_to_search = LENS_CATALOGS

    all_matched_data = {}

    v = Vizier(columns=["**", "_r", "_RAJ2000", "_DEJ2000"])
    v.ROW_LIMIT = -1

    for ra, dec, target_name in tqdm(target_list, desc="Scanning Lens Catalogs", unit="obj"):
        matched_data = []
        target_coord = SkyCoord(ra=ra * u.degree, dec=dec * u.degree, frame='icrs')

        for cat_name, cat_id in catalogs_to_search.items():
            try:
                result = v.query_region(
                    target_coord,
                    radius=search_radius * u.arcsec,
                    catalog=cat_id,
                    cache=False
                )

                if len(result) > 0:
                    for table in result:
                        table_name = table.meta.get('name', 'unknown')

                        for row in table:
                            sep = None

                            if '_RAJ2000' in table.colnames and '_DEJ2000' in table.colnames:
                                try:
                                    src_coord = SkyCoord(ra=row['_RAJ2000'] * u.deg, dec=row['_DEJ2000'] * u.deg,
                                                         frame='icrs')
                                    sep = target_coord.separation(src_coord).arcsec
                                except (ValueError, TypeError, KeyError) as e:
                                    print(f"[WARNING] Failed to compute separation from coords in {cat_name}: {type(e).__name__} - {e}")
                                    pass

                            if sep is None and '_r' in table.colnames and row['_r'] is not None:
                                try:
                                    unit = table['_r'].unit
                                    if unit:
                                        sep = (row['_r'] * u.Unit(unit)).to(u.arcsec).value
                                    else:
                                        sep = float(row['_r']) * 60.0
                                except (ValueError, TypeError, u.UnitConversionError) as e:
                                    print(f"[WARNING] Failed to convert separation value in {cat_name}: {type(e).__name__} - {e}")
                                    pass

                            if sep is not None and sep > search_radius:
                                continue
                            elif sep is None:
                                continue

                            if cat_name == "Gaia_GraL_I" and 'P' in table.colnames:
                                try:
                                    p_val = row['P']
                                    if p_val is not None and float(p_val) < 0.3:
                                        continue
                                except (ValueError, TypeError) as e:
                                    print(f"[WARNING] Failed to parse P value in {cat_name}: {type(e).__name__} - {e}")
                                    pass

                            row_dict = {
                                'origin_catalog_name': cat_name,
                                'origin_catalog_id': cat_id,
                                'sub_table_name': table_name
                            }

                            for col in table.colnames:
                                if col in ('_r', '_RAJ2000', '_DEJ2000'):
                                    continue
                                val = row[col]
                                if hasattr(val, 'mask') and val.mask:
                                    row_dict[col] = None
                                else:
                                    row_dict[col] = _convert_numpy_types(val)

                            if sep is not None:
                                row_dict['ra'] = float(src_coord.ra.deg)
                                row_dict['dec'] = float(src_coord.dec.deg)
                                row_dict['separation_arcsec'] = float(sep)

                            if sep is not None:
                                if sep < 3.0:
                                    row_dict['priority_tag'] = "HIGH_PRIORITY_GLSN_CANDIDATE"
                                else:
                                    row_dict['priority_tag'] = "POTENTIAL_LENS_ENVIRONMENT"

                            matched_data.append(row_dict)

            except (ValueError, KeyError, RuntimeError) as e:
                print(f"[ERROR] Error querying {cat_name} ({cat_id}): {type(e).__name__} - {e}")
                continue

        all_matched_data[target_name] = matched_data

    return all_matched_data

if __name__ == "__main__":
    # Example usage
    targets = [
        (128.9593, 40.731, "TEST_LENS_OBJECT_1"),
        (129.0, 41.0, "TEST_LENS_OBJECT_2"),
        (117.2749, 21.1506, "TEST_LENS_OBJECT_3"),
        (109.143748, 38.352253, "2025wny")
    ]

    results = lens_cross_match(targets, search_radius=15)
    online_results = lens_cross_match_online(targets, search_radius=15)

    print(f"Cross-match completed for {len(targets)} objects.")
    for name, matches in results.items():
        print(f"{name}: Found {len(matches)} matches within 15 arcseconds radius")
        for match in matches:
            print(match)
    for name, matches in online_results.items():
        print(f"{name}: Found {len(matches)} online matches within 15 arcseconds radius")
        for match in matches:
            print(match)