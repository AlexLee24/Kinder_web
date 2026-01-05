import os
import pathlib
import pyfiglet
import pandas as pd
import json
from tqdm import tqdm


from datetime import datetime, timezone, timedelta


from TNS_api_download import download_TNS_api, distribute_to_daily_files
from DETECT_flag_object import extract_flag_objects
from DESI_cross_match import desi_cross_match
from LENS_cross_match import lens_cross_match_hsu, lens_cross_match_karp
from DETECT_get_photometry import get_photometry, upload_photometry_to_db
from DETECT_tools import generate_light_curve_and_M
from DESI_image import create_marked_image

# Add parent directory to path to import postgres_database
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(parent_dir)
sys.path.append(os.path.join(parent_dir, 'modules'))

try:
    from postgres_database import init_tns_database, save_flag_objects, save_cross_match_results, get_cross_match_results, tns_object_db, save_target_image
except ImportError:
    print("Warning: Could not import postgres_database. Database operations may fail.")
    def init_tns_database(): pass
    def save_cross_match_results(r): pass
    def get_cross_match_results(date=None): return []
    def save_target_image(n, d): pass
    tns_object_db = None

# base_path = pathlib.Path("/Volumes/Mac_mini/Lab_Macmini/DETECT")
base_path = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))

def create_cross_match_list(today):
    yesterday = today - timedelta(days=1)
    d2_before = today - timedelta(days=2)
    d3_before = today - timedelta(days=3)

    
    
    d1_year, d1_month, d1_day = yesterday.year, yesterday.month, yesterday.day

    # download TNS data for yesterday
    print(f"Processing date: {d1_year}-{d1_month:02d}-{d1_day:02d}")
    print('-'*50)
    print("Downloading TNS data...")
    download_TNS_api(d1_year, d1_month, d1_day)
    distribute_to_daily_files(d1_year, d1_month, d1_day)

    # load data
    print('-'*50)
    print("Create cross-match object list...")
    print(f"Cross-matching object date from {d3_before.strftime('%Y-%m-%d')} to {yesterday.strftime('%Y-%m-%d')}")
    
    print('-'*50)
    print("Loading TNS daily data past three days...")
    tns_daily_dir = base_path / "data/tns_daily"
    dates_to_process = [yesterday, d2_before, d3_before]

    cross_match_objects = []

    for target_date in dates_to_process:
        y = target_date.year
        m = target_date.month
        
        date_str = target_date.strftime("%Y%m%d")
        csv_file = f"{tns_daily_dir}/{y}_{m:02d}/tns_public_objects_{date_str}.csv"
        
        if not os.path.exists(csv_file):
            print(f"No data file for date: {date_str}")
            continue
        
        df = pd.read_csv(csv_file)
        target_cols = ['name_prefix', 'name', 'ra', 'declination', 'discoverydate', 'internal_names']
        
        objects_list = df[target_cols].values.tolist()
        cross_match_objects.extend(objects_list)

    print('-'*50)
    print("Loading Flag data...")
    extract_flag_objects()
    flag_csv = base_path / "flag/Flag_Object_List.csv"
    if not os.path.exists(flag_csv):
        print(f"No data file for flag")
    else:
        try:
            df = pd.read_csv(flag_csv)
        except pd.errors.EmptyDataError:
            print("Flag file is empty, skipping flag objects")
            df = pd.DataFrame()
        
        if len(df) == 0:
            print("No flag objects to process")
        else:
            target_cols = ['name_prefix', 'name', 'ra', 'declination', 'discoverydate', 'internal_names']
            
            # Get existing names in cross_match_objects
            existing_names = set(obj[1] for obj in cross_match_objects)
            
            # Filter out objects that already exist
            flag_objects = df[target_cols].values.tolist()
            new_flag_objects = [obj for obj in flag_objects if obj[1] not in existing_names]
            
            if new_flag_objects:
                cross_match_objects.extend(new_flag_objects)
                print(f"Added {len(new_flag_objects)} new flag objects ({len(flag_objects) - len(new_flag_objects)} duplicates skipped)")
            else:
                print(f"All {len(flag_objects)} flag objects already in list")

    return cross_match_objects

def cross_match(cross_match_objects_list, today):
    # desi_directory = base_path / "Data_DESI_dir" # No longer needed with DB
    
    # ============================= DESI Cross-Match =============================
    print('-'*50)
    print(f"DESI cross-matching...")
    # Prepare output directory
    year = today.year
    month = today.month
    day = today.day
    
    output_dir = base_path / "daily_run" / "data" / "desi" / f"{year}_{month:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    desi_output_file = output_dir / f"desi_{year}{month:02d}{day:02d}.csv"
    
    matched_results = []
    
    for obj in tqdm(cross_match_objects_list, desc="DESI matching"):
        name_prefix, name, ra, dec, discoverydate, internal_names = obj
        
        # Updated to use DB-based cross match
        matches = desi_cross_match(ra, dec, name, search_radius=30)
        
        if matches:
            # Find closest match index for is_Host
            closest_idx = -1
            min_sep = float('inf')
            for i, m in enumerate(matches):
                try:
                    sep = float(m.get('separation_arcsec', 9999))
                    if sep < min_sep:
                        min_sep = sep
                        closest_idx = i
                except:
                    pass

            # Combine TNS object data with each match
            for i, match in enumerate(matches):
                combined_data = {
                    'tns_name_prefix': name_prefix,
                    'tns_name': name,
                    'tns_ra': ra,
                    'tns_dec': dec,
                    'tns_discoverydate': discoverydate,
                    'tns_internal_names': internal_names,
                    'is_Host': False, # Default to False, let user set it manually
                    **match  # Add all DESI match data
                }
                matched_results.append(combined_data)
    
    # Save matched results to CSV
    if matched_results:
        df_results = pd.DataFrame(matched_results)
        df_results.to_csv(desi_output_file, index=False)
        print(f"\nSaved {len(matched_results)} matched records to {desi_output_file}")
        
        # Save to DB
        print("Saving DESI matches to database...")
        save_cross_match_results(matched_results)
    else:
        print("\nNo matches found, no file created.")
    
    
    # ============================= Lens Cross-Match =============================
    print('-'*50)
    print(f"Lens cross-matching...")
    
    # Prepare Lens output directory
    lens_output_dir = base_path / "daily_run" / "data" / "lens" / f"{year}_{month:02d}"
    lens_output_dir.mkdir(parents=True, exist_ok=True)
    lens_output_file = lens_output_dir / f"lens_{year}{month:02d}{day:02d}.csv"
    
    lens_matched_results = []
    
    for obj in tqdm(cross_match_objects_list, desc="Lens matching"):
        name_prefix, name, ra, dec, discoverydate, internal_names = obj
        
        # Cross-match with both Hsu and Karp catalogs using DB
        matches_hsu = lens_cross_match_hsu(ra, dec, name, search_radius=15)
        matches_karp = lens_cross_match_karp(ra, dec, name, search_radius=15)
        
        # Process Hsu matches
        if matches_hsu:
            # Find closest match index
            closest_idx = -1
            min_sep = float('inf')
            for i, m in enumerate(matches_hsu):
                try:
                    sep = float(m.get('separation_arcsec', 9999))
                    if sep < min_sep:
                        min_sep = sep
                        closest_idx = i
                except:
                    pass

            for i, match in enumerate(matches_hsu):
                combined_data = {
                    'tns_name_prefix': name_prefix,
                    'tns_name': name,
                    'tns_ra': ra,
                    'tns_dec': dec,
                    'tns_discoverydate': discoverydate,
                    'tns_internal_names': internal_names,
                    'lens_catalog': 'Hsu',
                    'is_Host': False, # Default to False
                    **match
                }
                lens_matched_results.append(combined_data)
        
        # Process Karp matches
        if matches_karp:
            # Find closest match index
            closest_idx = -1
            min_sep = float('inf')
            for i, m in enumerate(matches_karp):
                try:
                    sep = float(m.get('separation_arcsec', 9999))
                    if sep < min_sep:
                        min_sep = sep
                        closest_idx = i
                except:
                    pass

            for i, match in enumerate(matches_karp):
                combined_data = {
                    'tns_name_prefix': name_prefix,
                    'tns_name': name,
                    'tns_ra': ra,
                    'tns_dec': dec,
                    'tns_discoverydate': discoverydate,
                    'tns_internal_names': internal_names,
                    'lens_catalog': 'Karp',
                    'is_Host': False, # Default to False
                    **match
                }
                lens_matched_results.append(combined_data)
    
    # Save Lens matched results to CSV
    if lens_matched_results:
        df_lens_results = pd.DataFrame(lens_matched_results)
        df_lens_results.to_csv(lens_output_file, index=False)
        print(f"Saved {len(lens_matched_results)} lens matched records to {lens_output_file}")
        
        # Save to DB
        print("Saving Lens matches to database...")
        save_cross_match_results(lens_matched_results)
    else:
        print("No lens matches found, no file created.")
    
    return desi_output_file, lens_output_file

def match_get_photometry(path_list):
    print('-'*50)
    print("Getting photometry for matched objects...")
    
    big_name_list = []
    
    for path in path_list:
        if not os.path.exists(path):
            print(f"File not found: {path}")
            continue
        
        df = pd.read_csv(path)
    
        # Extract required columns
        if 'tns_name' in df.columns and 'tns_ra' in df.columns and 'tns_dec' in df.columns and 'tns_internal_names' in df.columns:
            for _, row in df.iterrows():
                name = row['tns_name']
                ra = row['tns_ra']
                dec = row['tns_dec']
                internal_names = row['tns_internal_names']
                
                big_name_list.append([name, ra, dec, internal_names])
    
    # Remove duplicates based on name (after processing all files)
    seen_names = set()
    unique_name_list = []
    for item in big_name_list:
        if item[0] not in seen_names:
            seen_names.add(item[0])
            unique_name_list.append(item)
    
    print(f"Created list with {len(unique_name_list)} unique objects")
    print(unique_name_list)
    print('-'*50)
    get_photometry(unique_name_list, output_dir="data/photometry")
    
    # Upload to DB
    print("Uploading photometry to database...")
    for item in unique_name_list:
        name = item[0]
        year = name[:4]
        phot_file = pathlib.Path("data/photometry") / year / f"{name}_photometry.txt"
        if phot_file.exists():
            upload_photometry_to_db(name, str(phot_file))
        else:
            print(f"Photometry file not found for {name}: {phot_file}")
    
    return

def get_lc_and_M_desi(desi_path):
    print("Getting light curves and absolute magnitudes for matched objects...")
    if not os.path.exists(desi_path):
        print(f"File not found: {desi_path}")
        return
    
    df = pd.read_csv(desi_path)
    
    # Create columns for brightest magnitudes if they don't exist
    if 'brightest_mag' not in df.columns:
        df['brightest_mag'] = None
    if 'brightest_abs_mag' not in df.columns:
        df['brightest_abs_mag'] = None
    
    for idx, row in df.iterrows():
        name = row['tns_name']
        redshift = row['z']
        print(f"Processing {name} (redshift: {redshift})...")
        if pd.isna(redshift):
            print(f"Redshift not available for {name}, skipping...")
            continue
        
        try:
            path, brightest_mag, brightest_abs_mag = generate_light_curve_and_M(name, redshift, data_dir="data/photometry", output_dir="daily_run/data/light_curves")
            print(f"brightest_mag: {brightest_mag}, brightest_abs_mag: {brightest_abs_mag}")
            df.at[idx, 'brightest_mag'] = brightest_mag
            df.at[idx, 'brightest_abs_mag'] = brightest_abs_mag
        except Exception as e:
            print(f"Error generating light curve for {name}: {e}")
            continue
    
    # Save updated DataFrame back to CSV
    df.to_csv(desi_path, index=False)
    print(f"Updated {desi_path} with brightest magnitudes")
    
    return

def get_lc_and_M_lens(lens_path):
    print("Getting light curves and absolute magnitudes for matched objects...")
    if not os.path.exists(lens_path):
        print(f"File not found: {lens_path}")
        return
    
    df = pd.read_csv(lens_path)
    
    # Create columns for brightest magnitudes if they don't exist
    if 'brightest_mag' not in df.columns:
        df['brightest_mag'] = None
    if 'brightest_abs_mag' not in df.columns:
        df['brightest_abs_mag'] = None
    
    for idx, row in df.iterrows():
        name = row['tns_name']
        
        # Try to get redshift from Hsu catalog first, then Karp
        redshift_hsu = row.get('z_source', None)
        redshift_karp = row.get('z', None)
        
        # Select first available non-NaN redshift
        if pd.notna(redshift_hsu) and redshift_hsu != 'nan':
            redshift = redshift_hsu
        elif pd.notna(redshift_karp) and redshift_karp != 'nan':
            redshift = redshift_karp
        else:
            redshift = None
        
        print(f"Processing {name} (redshift: {redshift})...")
        
        if redshift is None or pd.isna(redshift):
            print(f"Redshift not available for {name}, skipping...")
            continue
        
        try:
            path, brightest_mag, brightest_abs_mag = generate_light_curve_and_M(name, redshift, data_dir="data/photometry", output_dir="daily_run/data/light_curves")
            print(f"brightest_mag: {brightest_mag}, brightest_abs_mag: {brightest_abs_mag}")
            df.at[idx, 'brightest_mag'] = brightest_mag
            df.at[idx, 'brightest_abs_mag'] = brightest_abs_mag
        except Exception as e:
            #print(f"Error generating light curve for {name}: {e}")
            continue
    
    # Save updated DataFrame back to CSV
    df.to_csv(lens_path, index=False)
    print(f"Updated {lens_path} with brightest magnitudes")
    
    return

def download_DESI_images(date=None):
    print('-'*50)
    print(f"Downloading DESI images for matched objects from database (Date: {date})...")
    # output_dir = base_path / "daily_run" / "data" / "DETECT_images"
    # output_dir = pathlib.Path("/Volumes/Mac_mini/Lab_Macmini/GitHub_Work/kinder_web/app/modules/DETECT_pipe/modules/data/DESI_img")
    output_dir = base_path / "data" / "DESI_img"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get results from DB
    results = get_cross_match_results(date=date)
    
    if not results:
        print("No cross match results found in database.")
        return

    # Collect all objects and their target coordinates
    objects_dict = {}  # {obj_name: {'obj_ra': ra, 'obj_dec': dec, 'targets': [...]}}
    seen_targets = {}  # {obj_name: set((ra, dec))}
    
    for row in results:
        obj_name = row.get('target_name')
        if not obj_name:
            continue
            
        # Get TNS info
        tns_info = tns_object_db.get_object_details(obj_name)
        if not tns_info:
            print(f"Could not find TNS info for {obj_name}")
            continue
            
        obj_ra = tns_info.get('ra')
        obj_dec = tns_info.get('declination')
        
        if obj_ra is None or obj_dec is None:
            continue
            
        # Parse match data
        match_data = row.get('match_data')
        if isinstance(match_data, str):
            try:
                match_data = json.loads(match_data)
            except:
                continue
        elif not isinstance(match_data, dict):
            continue
            
        # Extract target info
        # Different catalogs might have different field names
        target_ra = match_data.get('ra') or match_data.get('match_ra')
        target_dec = match_data.get('dec') or match_data.get('match_dec')
        
        if target_ra is None or target_dec is None:
            continue
            
        target_ra = float(target_ra)
        target_dec = float(target_dec)
        
        target_z = match_data.get('z') or match_data.get('Z') or match_data.get('redshift') or match_data.get('z(s)') or 'N/A'
        target_id = match_data.get('TARGETID') or match_data.get('id') or 'Unknown'
        
        # Initialize if first time seeing this object
        if obj_name not in objects_dict:
            objects_dict[obj_name] = {
                'obj_ra': obj_ra,
                'obj_dec': obj_dec,
                'targets': []
            }
            seen_targets[obj_name] = set()
        
        # Deduplicate
        target_key = (round(target_ra, 5), round(target_dec, 5))
        if target_key in seen_targets[obj_name]:
            continue
        seen_targets[obj_name].add(target_key)
        
        # Create target dict with required format
        target_dict = {
            'ra': target_ra,
            'dec': target_dec,
            'redshift': target_z,
            'name': f'TARGET_{target_id}'
        }
        
        objects_dict[obj_name]['targets'].append(target_dict)
    
    # Create marked images for each unique object
    print(f"Creating marked images for {len(objects_dict)} unique objects...")
    for obj_name, obj_data in tqdm(objects_dict.items(), desc="Creating images"):
        obj_ra = obj_data['obj_ra']
        obj_dec = obj_data['obj_dec']
        target_coord_list = obj_data['targets']
        
        # Generate output path (optional, for local backup if needed, but we want DB)
        # year = obj_name[:4]
        # output_dir_year = output_dir / year
        # output_dir_year.mkdir(parents=True, exist_ok=True)
        # output_path = output_dir_year / f"{obj_name}_marked.png"
        
        try:
            # Create image in memory
            image_bytes = create_marked_image(obj_name, obj_ra, obj_dec, target_coord_list, output_path=None)
            
            # Save to DB
            if save_target_image(obj_name, image_bytes):
                print(f"Created and saved image for {obj_name} with {len(target_coord_list)} target(s) to DB")
            else:
                print(f"Failed to save image for {obj_name} to DB")
                
        except Exception as e:
            print(f"Error creating image for {obj_name}: {e}")
            continue
    
    return

def daily_run():
    import time
    
    # Ensure DB is initialized
    try:
        init_tns_database()
    except Exception as e:
        print(f"Warning: Database initialization failed: {e}")

    today = datetime.now(timezone.utc)
    print(pyfiglet.figlet_format("DETECT", font="slant"))
    print(pyfiglet.figlet_format(f"{today.year}-{today.month:02d}-{today.day:02d}", font="slant"))
    
    print('='*100)
    # Create cross-match list
    cm_list_start = time.time()
    
    cross_match_objects = create_cross_match_list(today)
    print(f"Objects to cross-match: {len(cross_match_objects)}")
    
    # Upload flag objects to DB
    print('-'*50)
    print("Uploading flag objects to database...")
    flag_csv = base_path / "flag/Flag_Object_List.csv"
    if flag_csv.exists():
        try:
            flag_df = pd.read_csv(flag_csv)
            target_cols = ['name_prefix', 'name', 'ra', 'declination', 'discoverydate', 'internal_names']
            if all(col in flag_df.columns for col in target_cols):
                flag_list = flag_df[target_cols].values.tolist()
                save_flag_objects(flag_list)
                # print("Skipping save_flag_objects (module missing)")
        except Exception as e:
            print(f"Error saving flag objects to DB: {e}")
    
    cm_list_end = time.time()
    cm_list_duration = cm_list_end - cm_list_start
    
    
    print('='*100)
    # Perform cross-match
    cross_match_start = time.time()
    
    desi_output_file, lens_output_file = cross_match(cross_match_objects, today)
    
    cross_match_end = time.time()
    cross_match_duration = cross_match_end - cross_match_start
    
    
    print('='*100)
    # Get photometry for matched objects
    match_photometry_start = time.time()
    
    match_get_photometry([desi_output_file, lens_output_file])
    
    # Upload photometry to DB
    print('-'*50)
    print("Uploading photometry to database...")
    # Photometry is already uploaded by get_photometry (via process_single_object_workflow)
    # So we don't need to do it manually here.
    
    match_photometry_end = time.time()
    match_photometry_duration = match_photometry_end - match_photometry_start
    
    
    print('='*100)
    # Get light curves and absolute magnitudes
    # get_lc_and_M_start = time.time()
    
    # get_lc_and_M_desi(desi_output_file)
    # get_lc_and_M_lens(lens_output_file)
    
    # get_lc_and_M_end = time.time()
    # get_lc_and_M_duration = get_lc_and_M_end - get_lc_and_M_start
    get_lc_and_M_duration = 0
    
    
    print('='*100)
    # Download DESI Image
    download_images_start = time.time()
    
    download_DESI_images(today.strftime('%Y-%m-%d'))
    
    download_images_end = time.time()
    download_images_duration = download_images_end - download_images_start
    
    print('='*100)
    # Generate HTML and PDF report
    # report_start = time.time()
    # report_file = generate_html_report([desi_output_file, lens_output_file])
    # pdf_file = generate_pdf_report(report_file)
    # report_end = time.time()
    # report_duration = report_end - report_start
    report_duration = 0
    
    # Upload results to DB
    print('-'*50)
    print("Uploading results to database...")
    # Results are already uploaded to cross_match_results table during cross_match
    # So we don't need to do it manually here.
    
    print('='*100)
    print("Daily run summary:")
    print('-'*100)
    print(f"Objects to cross-match: {len(cross_match_objects)}")
    print('-'*100)
    print(f"Cross-match list creation time: {cm_list_duration:.2f} seconds")
    print(f"Cross-matching time: {cross_match_duration:.2f} seconds")
    print(f"Photometry retrieval time: {match_photometry_duration:.2f} seconds")
    print(f"Light curve and M calculation time: {get_lc_and_M_duration  :.2f} seconds")
    print(f"DESI image download time: {download_images_duration:.2f} seconds")
    print(f"Report generation time: {report_duration:.2f} seconds")
    print('='*100)
    print(pyfiglet.figlet_format("DETECT FINISHED", font="slant"))
    return 

if __name__ == "__main__":
    # extract_flag_objects()  
    
    # Immediate execution for testing
    print("Executing daily_run immediately for testing...")
    daily_run()
    
    # Scheduler logic (commented out for now, or active if desired)
    # import time
    # print("Starting scheduler for UTC 02:00 daily run...")
    # while True:
    #     now = datetime.now(timezone.utc)
    #     target_time = now.replace(hour=2, minute=0, second=0, microsecond=0)
    #     if now >= target_time:
    #         target_time += timedelta(days=1)
    #     
    #     wait_seconds = (target_time - now).total_seconds()
    #     print(f"Waiting {wait_seconds/3600:.2f} hours until next run at {target_time} UTC")
    #     time.sleep(wait_seconds)
    #     
    #     daily_run()
    #     time.sleep(60) 
