from datetime import datetime, timezone
import requests
import os
from pathlib import Path
from dotenv import load_dotenv
import zipfile


def download_tns_data():
    load_dotenv()
    
    # Get current UTC hour
    utc_hr = f"{datetime.now(timezone.utc).hour:02d}"
    
    # Setup paths and URLs - use app-level tns_data directory
    tns_data_dir = Path(os.path.dirname(os.path.dirname(__file__))) / "tns_data"
    tns_data_dir.mkdir(exist_ok=True)
    
    # Correct TNS URL format with .csv.zip extension
    tns_link = f"https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{utc_hr}.csv.zip"
    
    #all
    #tns_link = f"https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects.csv.zip"
    
    # Setup headers
    tns_bot_id = os.getenv('TNS_BOT_ID')
    tns_bot_name = os.getenv('TNS_BOT_NAME')
    headers = {
        'User-Agent': f'tns_marker{{"tns_id":"{tns_bot_id}","type":"bot","name":"{tns_bot_name}"}}'
    }
    
    try:
        print(f"Downloading TNS data from: {tns_link}")
        print(f"Saving to directory: {tns_data_dir}")
        
        # Download file
        response = requests.get(tns_link, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Save and extract with correct filename
        filename = f"tns_public_objects_{utc_hr}.csv.zip"
        file_path = tns_data_dir / filename
        
        with open(file_path, 'wb') as f:
            f.write(response.content)
        
        print(f"Downloaded {len(response.content)} bytes")
        
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            file_list = zip_ref.namelist()
            print(f"Files in ZIP: {file_list}")
            zip_ref.extractall(tns_data_dir)
        
        # Clean up zip file
        file_path.unlink()
        
        print(f"TNS data downloaded and extracted successfully")
        
    except requests.RequestException as e:
        print(f"Error downloading TNS data: {e}")
        raise e
    except zipfile.BadZipFile as e:
        print(f"Error extracting zip file: {e}")
        raise e
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise e


if __name__ == "__main__":
    download_tns_data()