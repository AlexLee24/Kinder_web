import os
import pathlib
import requests
import json
import zipfile
import pandas as pd
import time
from datetime import datetime

# ---- User settings ----
current_dir = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
SAVE_DIR = current_dir / "data" / "tns_api_download_work"
TNS_DIR = current_dir / "data" / "tns_daily"
SAVE_DIR.mkdir(parents=True, exist_ok=True)
TNS_DIR.mkdir(parents=True, exist_ok=True)

# ---- BOT settings ----
from dotenv import load_dotenv
project_root = os.path.dirname(os.path.abspath(__file__))
# dotenv_path = "/Volumes/Mac_mini/Lab_Macmini/DETECT/.env"
dotenv_path = os.path.join(project_root, "../../../../kinder.env")
load_dotenv(dotenv_path)
env = os.getenv
tns_host     = env("TNS_HOST")
api_base_url = env("API_BASE_URL")
bot_id       = env("TNS_BOT_ID")
bot_name     = env("TNS_BOT_NAME")
api_key      = env("TNS_API_KEY") 

# ---- Function to download TNS API data ----
def download_TNS_api(year, month, day, debug=False):
    download_url = f"https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{year}{month:02d}{day:02d}.csv.zip"
    
    # Set headers with bot info
    headers = {
        'user-agent': f'tns_marker{{"tns_id":{bot_id},"type":"bot","name":"{bot_name}"}}'
    }
    
    # Set POST data
    data = {
        'api_key': api_key
    }
    
    if debug:
        print(f"URL: {download_url}")
        print(f"Headers: {headers}")
    
    # Retry logic: 10s, 30s, 60s
    retry_delays = [10, 30, 60]
    attempt = 0
    max_attempts = len(retry_delays) + 1
    
    while attempt < max_attempts:
        if attempt > 0:
            delay = retry_delays[attempt - 1]
            print(f"Waiting {delay} seconds before retry {attempt}/{len(retry_delays)}...")
            time.sleep(delay)
        
        response = requests.post(download_url, headers=headers, data=data)
        
        if response.status_code == 200:
            output_file = SAVE_DIR / f"tns_public_objects_{year}{month:02d}{day:02d}.csv.zip"
            with open(output_file, 'wb') as f:
                f.write(response.content)
            if debug:
                print(f"Data successfully saved to: {output_file}")
            
            # Unzip the file
            with zipfile.ZipFile(output_file, 'r') as zip_ref:
                zip_ref.extractall(SAVE_DIR)
            if debug:
                print(f"File unzipped to: {SAVE_DIR}")
            
            # Rename the extracted CSV file
            extracted_csv = SAVE_DIR / f"tns_public_objects_{year}{month:02d}{day:02d}.csv"
            #renamed_csv = SAVE_DIR / f"tns_public_objects_WORK_{year}{month:02d}{day:02d}_WORK.csv"
            renamed_csv = SAVE_DIR / f"tns_public_objects_WORK.csv"
            if extracted_csv.exists():
                if renamed_csv.exists():
                    renamed_csv.unlink()
                extracted_csv.rename(renamed_csv)
                if debug:
                    print(f"Renamed extracted file to: {renamed_csv}")
            
            # Remove the zip file
            output_file.unlink()
            if debug:
                print(f"Removed zip file: {output_file}")
            print(f"Download and extraction completed for {year}-{month:02d}-{day:02d}")
            return True
        elif response.status_code == 404:
            print(f"Error: File not found (404) for {year}-{month:02d}-{day:02d}")
            return False
        else:
            print(f"Error: Request failed with status code: {response.status_code}")
            attempt += 1
            if attempt >= max_attempts:
                print(f"Failed after {len(retry_delays)} retries. Stopping.")
                return False

def distribute_to_daily_files(year, month, day, debug=False):
    work_csv = SAVE_DIR / f"tns_public_objects_WORK.csv"
    
    if not work_csv.exists():
        print(f"Error: Work CSV file not found: {work_csv}")
        return False
    
    print(f"Reading work file: {work_csv}")
    
    # Skip first row (date range) and use second row as header
    df = pd.read_csv(work_csv, skiprows=1)
    
    # Strip quotes from column names if present
    df.columns = df.columns.str.strip().str.replace('"', '')
    if debug:
        print(f"Total objects loaded: {len(df)}")
    
    # Filter out FRB objects
    if 'name_prefix' in df.columns:
        initial_count = len(df)
        df = df[df['name_prefix'] != 'FRB']
        frb_count = initial_count - len(df)
    
    if 'discoverydate' not in df.columns:
        print(f"Error: 'discoverydate' column not found. Available columns: {df.columns.tolist()}")
        return False
    
    # Parse discoverydate and group by date
    df['discoverydate'] = pd.to_datetime(df['discoverydate'])
    
    # Show discoverydate range
    grouped = df.groupby(df['discoverydate'].dt.date)
    
    if debug:
        print(f"Discovery date range: {df['discoverydate'].min()} to {df['discoverydate'].max()}")
        print(f"Total unique dates: {len(grouped)}")
    
    created_count = 0
    updated_count = 0
    new_objects_count = 0
    updated_objects_count = 0
    
    for date, group_df in grouped:
        year = date.year
        month = date.month
        day = date.day
        
        # Create directory
        date_dir = TNS_DIR / f"{year}_{month:02d}"
        date_dir.mkdir(parents=True, exist_ok=True)
        
        # Output file path
        output_csv = date_dir / f"tns_public_objects_{year}{month:02d}{day:02d}.csv"
        
        # Check if file exists
        if output_csv.exists():
            existing_df = pd.read_csv(output_csv)
            
            # Identify new vs updated objects
            if 'Name' in existing_df.columns and 'Name' in group_df.columns:
                existing_names = set(existing_df['Name'])
                new_names = set(group_df['Name'])
                
                new_in_batch = len(new_names - existing_names)
                updated_in_batch = len(new_names & existing_names)
                
                new_objects_count += new_in_batch
                updated_objects_count += updated_in_batch
            
            # Combine all data
            combined_df = pd.concat([existing_df, group_df], ignore_index=True)
            
            # Remove duplicates based on Name, keep last (newest data)
            if 'Name' in combined_df.columns:
                combined_df = combined_df.drop_duplicates(subset=['Name'], keep='last')
            
            combined_df.to_csv(output_csv, index=False)
            updated_count += 1
            if debug:
                print(f"Updated: {output_csv} (+{new_in_batch} new, ~{updated_in_batch} updated)")
        else:
            group_df.to_csv(output_csv, index=False)
            created_count += 1
            new_objects_count += len(group_df)
            if debug:
                print(f"Created: {output_csv} ({len(group_df)} records)")
    
    # Update work.csv with filtered data (FRB removed)
    with open(work_csv, 'r') as f:
        first_line = f.readline()
    
    # Sort by discoverydate in descending order (newest first)
    df = df.sort_values('discoverydate', ascending=False)
    
    with open(work_csv, 'w') as f:
        f.write(first_line)
        df.to_csv(f, index=False)
    
    if debug:
        print(f"Updated work.csv: {len(df)} objects (FRB excluded)")
        print(f"Distribution: {created_count} files created, {updated_count} files updated")
        print(f"Objects: +{new_objects_count} new, ~{updated_objects_count} updated")
        print(f"\nDistribution summary:")
        print(f"  Created: {created_count} file(s)")
        print(f"  Updated: {updated_count} file(s)")
        print(f"  Total: {created_count + updated_count} file(s)")
    
    return True

if __name__ == "__main__":
    year, month, day = 2026, 1, 2
    download_TNS_api(year, month, day, debug=False)
    distribute_to_daily_files(year, month, day, debug=False)