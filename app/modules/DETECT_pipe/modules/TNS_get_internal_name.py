import os
import pathlib
import requests
import json
import zipfile
import pandas as pd
import time
from datetime import datetime


from dotenv import load_dotenv
project_root = os.path.dirname(os.path.abspath(__file__))
# dotenv_path = "/Volumes/Mac_mini/Lab_Macmini/DETECT/.env"
dotenv_path = os.path.join(project_root, "../../../../kinder.env")
load_dotenv(dotenv_path)
env = os.getenv
tns_host     = env("TNS_HOST")
api_base_url = env("API_BASE_URL")
TNS_BOT_ID       = env("BOT_ID")
TNS_BOT_NAME     = env("BOT_NAME")
TNS_API_KEY      = env("API_KEY") 


TARGET_NAME = "2025zmn" 

def get_tns_internal_name(objname):
    url = "https://www.wis-tns.org/api/get/object"
    
    tns_marker = f'tns_marker{{"tns_id":{TNS_BOT_ID},"type":"bot","name":"{TNS_BOT_NAME}"}}'
    headers = {
        "User-Agent": tns_marker
    }

    search_data = {
        "objname": objname,
        "photometry": "0",
        "spectra": "0"
    }
    
    payload = {
        "api_key": TNS_API_KEY,
        "data": json.dumps(search_data)
    }

    try:
        response = requests.post(url, headers=headers, data=payload)
        
        if response.status_code != 200:
            print(f"Error: HTTP {response.status_code}")
            print("Server response:", response.text)
            return

        json_data = response.json()
        
        if "id_code" in json_data and json_data["id_code"] != 200:
             print(f"API Error: {json_data.get('id_message')}")
             return

        data = json_data.get("data", {})
        
        if not data:
            print("No data found (possibly incorrect target name or permission issue)")
            return []

        internal_names = data.get("internal_names")
        
        if internal_names:
            name_list = [name.strip() for name in internal_names.split(',')]
            return name_list
        else:
            print("No Internal Name record for this target.")
            return []

    except Exception as e:
        print(f"Exception occurred: {e}")

if __name__ == "__main__":
    name = get_tns_internal_name("2025ajvp")
    print(f"Internal names for 2025ajvp: {name}")