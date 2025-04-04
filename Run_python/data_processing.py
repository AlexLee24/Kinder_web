import os
import numpy as np
import datetime
import shutil
import csv
import plotly.graph_objects as go
import configparser

import requests
from bs4 import BeautifulSoup
import time

config = configparser.ConfigParser()
config.read('config_file.ini')
BASE_DIR = config['Paths']['BASE_DIR']

DATA_PATH = os.path.join(BASE_DIR, 'Lab_Data')
DATA_FILE = os.path.join(BASE_DIR,'Other', 'observations.csv')

STATIC_IMAGE_FOLDER = '/Data_img'
STATIC_IMAGE_FOLDER_Direct = os.path.join(BASE_DIR, 'Data_img')

base_upload_folder = os.path.join(BASE_DIR, 'Lab_Data') 

# Interactive plot, spec ============================================
def create_interactive_spectrum_plot(spectrum_file, plot_filename):
    data = np.loadtxt(spectrum_file, usecols=(0, 1))
    wavelength, intensity = data[:, 0], data[:, 1]

    trace = go.Scatter(x=wavelength, y=intensity, mode='lines', name='Spectra')
    layout = go.Layout(
        title="Spectra",
        xaxis=dict(title="Wavelength (Å)"),
        yaxis=dict(title="Intensity"),
        template="seaborn"
    )
    fig = go.Figure(data=[trace], layout=layout)

    # Save the interactive plot as an HTML file
    fig.write_html(plot_filename)

# Interactive plot, photometry ============================================
def get_filter_color(filter_name, alpha):
    filter_colors = {
        # Swift UVOT 濾鏡（近似值）
        'uvw2': f'rgba(106,90,205,－)',  # 藍紫色
        'uvm2': f'rgba(132,112,255,{alpha})', # 淡紫藍
        'uvw1': f'rgba(123,104,238,{alpha})', # 藍紫

        # 光學濾鏡（SDSS/Johnson 系統）
        'u': f'rgba(75,0,130,{alpha})',        # U 濾鏡：靛藍色
        'B': f'rgba(0,0,255,{alpha})',         # B 濾鏡：藍色
        'g': f'rgba(44,164,112,{alpha})',       # g 濾鏡：偏綠（綠色調）
        'V': f'rgba(34,139,34,{alpha})',        # V 濾鏡：正綠
        'r': f'rgba(255,100,100,{alpha})',      # 小寫 r（例如 SDSS r）：偏紅
        'R': f'rgba(255,0,0,{alpha})',          # 大寫 R（例如 Johnson R）：紅色
        'o': f'rgba(255,165,0,{alpha})',        # o 濾鏡：橙色
        'i': f'rgba(255,105,180,{alpha})',      # i 濾鏡：粉紅 
        'z': f'rgba(139,0,0,{alpha})',          # z 濾鏡：深紅
        'y': f'rgba(210,105,30,{alpha})',       # y 濾鏡：棕橘色
        'w': f'rgba(46,139,87,{alpha})',        # w 濾鏡：綠意較重（或視為白光輔助）
        'c': f'rgba(138,43,226,{alpha})',       # c 濾鏡：藍紫

        # 紅外線濾鏡
        'J': f'rgba(139,69,19,{alpha})',        # J 濾鏡：棕色
        'H': f'rgba(160,82,45,{alpha})',        # H 濾鏡：土紅
        'Ks': f'rgba(205,133,63,{alpha})'       # Ks 濾鏡：黃土色
    }
    return filter_colors.get(filter_name, f'rgba(0,0,0,－)')


def create_interactive_photometry_plot(photometry_files, plot_filename):
    traces = []
    marker_symbols_list = ['square', 'diamond', 'cross', 'x', 'star']
    marker_symbols = {}

    combined_data = {}
    
    for photometry_file, filter_name in photometry_files.items():
        if '+' in filter_name:
            filter_name, telescope = filter_name.split('+')
        else:
            telescope = 'Unknown'
        
        data = np.loadtxt(photometry_file, usecols=(0, 1, 2))
        if data.ndim == 1:
            data = np.expand_dims(data, axis=0)
        time, mag, error = data[:, 0], data[:, 1], data[:, 2]

        if filter_name not in combined_data:
            combined_data[filter_name] = {'time': [], 'mag': [], 'error': [], 'telescope': []}
        combined_data[filter_name]['time'].extend(time)
        combined_data[filter_name]['mag'].extend(mag)
        combined_data[filter_name]['error'].extend(error)
        combined_data[filter_name]['telescope'].extend([telescope] * len(time))
    
    for filter_name, data in combined_data.items():
        for telescope in set(data['telescope']):
            if telescope not in marker_symbols:
                if telescope == 'Unknown':
                    marker_symbols[telescope] = 'circle'
                else:
                    if marker_symbols_list:
                        marker_symbols[telescope] = marker_symbols_list.pop(0)
                    else:
                        marker_symbols[telescope] = 'circle'
            
            group_indices = [i for i, t in enumerate(data['telescope']) if t == telescope]
            indices_with_error = [i for i in group_indices if abs(data['error'][i]) > 0]
            indices_without_error = [i for i in group_indices if abs(data['error'][i]) == 0]
            
            if indices_with_error:
                colors_with = [get_filter_color(filter_name, 1) for _ in indices_with_error]
                trace_with = go.Scatter(
                    x=[data['time'][i] for i in indices_with_error],
                    y=[data['mag'][i] for i in indices_with_error],
                    mode='markers',
                    name=f'Filter: {filter_name} (Telescope: {telescope})',
                    marker=dict(
                        color=colors_with,
                        symbol=marker_symbols[telescope],
                        size=10
                    ),
                    error_y=dict(
                        type='data',
                        array=[abs(data['error'][i]) for i in indices_with_error],
                        visible=True,
                        color=get_filter_color(filter_name, 1)
                    ),
                    visible=True
                )
                traces.append(trace_with)
            
            if indices_without_error:
                colors_without = [get_filter_color(filter_name, 1) for _ in indices_without_error]
                symbols_without = ["triangle-down-open" for _ in indices_without_error]
                trace_without = go.Scatter(
                    x=[data['time'][i] for i in indices_without_error],
                    y=[data['mag'][i] for i in indices_without_error],
                    mode='markers',
                    name=f'Filter: {filter_name} (Telescope: {telescope}) (upper limits)',
                    marker=dict(
                        color=colors_without,
                        line=dict(
                            width=2,
                        ),
                        symbol=symbols_without,
                        size=10
                    ),
                    visible=True
                )
                traces.append(trace_without)
    
    layout = go.Layout(
        title="Photometry - Multiple Filters by clicking on the chart legend.",
        xaxis=dict(title="Time (MJD)", tickformat=".2f"),
        yaxis=dict(title="Magnitude", tickformat=".2f", autorange="reversed"),
        template="seaborn",
        showlegend=True
    )
    
    fig = go.Figure(data=traces, layout=layout)
    fig.write_html(plot_filename)

    
# =====================================================================
def scan_photometry_files(data_path, obj_folder):
    photometry_folder = os.path.join(data_path, obj_folder, "Photometry")
    photometry_files = {}
    
    if os.path.exists(photometry_folder):
        for file_name in os.listdir(photometry_folder):
            obj_part = obj_folder.split(" ")
            if len(obj_part) > 1:
                obj = f"{obj_part[0]}{obj_part[1]}"
            else:
                obj = f"{obj_part[0]}"
            if (file_name.startswith(f"{obj_folder}_") or file_name.startswith(f"{obj}_")) and file_name.endswith(".txt"):
                file_part = file_name.split("_")
                filter_name = file_part[1]
                path = os.path.join(photometry_folder, file_name)
                if len(file_part) > 3:
                    if '.txt' in file_part[3]:
                        Telescope = file_part[3].rstrip('.txt')
                    else:
                        Telescope = file_part[3]
                    photometry_files[path] = f"{filter_name}+{Telescope}"
                else:
                    photometry_files[path] = filter_name
        return photometry_files
    else:
        return None


class Data_Process:
    # Loading observation
    def load_data():
        data = []
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, newline='', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    data.append(row)
        return data

    # Save observation to csv
    def save_data(data):
        with open(DATA_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerows(data)

    # process_data_folders
    def process_data_folders(data_path=DATA_PATH):
        txt_paths = []
        for obj_folder in os.listdir(data_path):
            obj_path = os.path.join(data_path, obj_folder, 'Data', f"{obj_folder}_info.txt")
            # Add absolute path of txt file if it exists
            if os.path.exists(obj_path):
                txt_paths.append(os.path.abspath(obj_path))  
        return txt_paths

    # scan folder to get detail
    def scan_data_folders(data_path=DATA_PATH):
        objects = []

        for obj_folder in os.listdir(data_path):
            obj_path = os.path.join(data_path, obj_folder, "Data")
            txt_file_path = os.path.join(obj_path, f"{obj_folder}_info.txt")
            photometry_path = scan_photometry_files(data_path, obj_folder)
            spectrum_folder = os.path.join(data_path, obj_folder, "Spectrum")
            spectrum_path = None
            if os.path.exists(spectrum_folder):
                for file_name in os.listdir(spectrum_folder):
                    if file_name.endswith(".dat"):
                        spectrum_path = os.path.join(spectrum_folder, f"{obj_folder}_spectrum.dat")
                        break
                    elif file_name.endswith(".txt"):
                        spectrum_path = os.path.join(spectrum_folder, f"{obj_folder}_spectrum.txt")
                        break

            if os.path.exists(txt_file_path):
                last_update_date = datetime.datetime.fromtimestamp(os.path.getmtime(txt_file_path)).strftime('%Y-%m-%d %H:%M:%S')
                sp = str(spectrum_path)
                if not os.path.exists(sp):
                    spectrum_path = None
                with open(txt_file_path, 'r') as file:
                    lines = file.readlines()
                    ra = lines[0].split(": ")[1].strip()
                    dec = lines[1].split(": ")[1].strip()
                    photo_image_path = os.path.normpath(os.path.join(obj_path, lines[2].split(": ")[1].strip()))
                    TNtype = lines[3].split(": ")[1].strip() 
                    permission = lines[4].split(": ")[1].strip()
                    
                    # create static
                    object_static_folder = os.path.join(STATIC_IMAGE_FOLDER, obj_folder)
                    object_static_folder_direct = os.path.join(STATIC_IMAGE_FOLDER_Direct, obj_folder)
                    os.makedirs(object_static_folder_direct, exist_ok=True)

                    # copy file to static only if photo_image_path is not empty and is a file
                    photo_dest = os.path.join(object_static_folder, f"{obj_folder}_photo.png")
                    photo_dest_dir = os.path.join(object_static_folder_direct, f"{obj_folder}_photo.png")

                    if photo_image_path and os.path.isfile(photo_image_path):
                        shutil.copy(photo_image_path, photo_dest_dir)
                        web_photo_path = f"{photo_dest.replace(os.path.sep, '/')}"
                    else:
                        web_photo_path = None

                    # create interactive plot
                    spectrum_html_path = os.path.join(object_static_folder, f"{obj_folder}_spectrum.html")
                    spectrum_html_path_dir = os.path.join(object_static_folder_direct, f"{obj_folder}_spectrum.html")
                    if spectrum_path:
                        create_interactive_spectrum_plot(spectrum_path, spectrum_html_path_dir)
                        web_spectrum_html_path = f"{spectrum_html_path.replace(os.path.sep, '/')}"
                    else:
                        web_spectrum_html_path = None
                        
                    
                    photometry_html_path = os.path.join(object_static_folder, f"{obj_folder}_photometry.html")
                    photometry_html_path_dir = os.path.join(object_static_folder_direct, f"{obj_folder}_photometry.html")
                    if photometry_path:
                        create_interactive_photometry_plot(photometry_path, photometry_html_path_dir)
                        web_photometry_html_path = f"{photometry_html_path.replace(os.path.sep, '/')}"
                    else:
                        web_photometry_html_path = None

                    # analyze dat
                    if spectrum_path:
                        dat_file = next((f for f in os.listdir(os.path.join(data_path, obj_folder, "Spectrum")) if f.endswith('.dat')), None)
                        if dat_file:
                            dat_file_path = os.path.join(data_path, obj_folder, "Spectrum", dat_file)
                            dat_dest = os.path.join(object_static_folder, f"{obj_folder}_spectrum.dat")
                            dat_dest_dir = os.path.join(object_static_folder_direct, f"{obj_folder}_spectrum.dat")
                            shutil.copy(dat_file_path, dat_dest_dir)
                            web_dat_path = f"/{dat_dest.replace(os.path.sep, '/')}"
                        else:
                            web_dat_path = None
                    else:
                        web_dat_path = None
                    
                    object_data = {
                        'object_name': obj_folder,
                        'RA': ra,
                        'DEC': dec,
                        'last_update_date': last_update_date,
                        'TNtype': TNtype,
                        'Permission': permission
                    }
                    if web_photometry_html_path is not None:
                        object_data['photometry_html'] = web_photometry_html_path

                    if web_dat_path is not None:
                        object_data['dat_file'] = web_dat_path

                    if web_spectrum_html_path is not None:
                        object_data['spectrum_html'] = web_spectrum_html_path

                    if web_photo_path is not None:
                        object_data['photo_image'] = web_photo_path

                    objects.append(object_data)
            else:
                if not obj_folder == '.DS_Store':
                    objects.append({
                        'object_name': obj_folder,
                        'RA': None,
                        'DEC': None,
                        'last_update_date': None,
                        'photo_image': None,
                        'spectrum_html': None,
                        'photometry_html': None,
                        'dat_file': None,
                        'TNtype': None,
                        'Permission': None
                    })
        return objects

    def get_timezone_name(offset):
        timezone_dict = {
            0: 'UTC',
            1: 'Europe/Paris',
            2: 'Europe/Amsterdam',
            3: 'Europe/Moscow',
            4: 'Asia/Dubai',
            5: 'Asia/Karachi',
            6: 'Asia/Kolkata',
            7: 'Asia/Kuala_Lumpur',
            8: 'Asia/Taipei',
            9: 'Asia/Tokyo',
            10: 'Australia/Sydney',
            11: 'Pacific/Guam',         
            12: 'Pacific/Fiji',        
            -1: 'Atlantic/Azores',
            -2: 'Atlantic/Cape_Verde',
            -3: 'America/Argentina/Buenos_Aires',
            -4: 'America/New_York',
            -5: 'America/Chicago',
            -6: 'America/Mexico_City',
            -7: 'America/Denver',
            -8: 'America/Los_Angeles',
            -9: 'America/Anchorage',
            -10: 'Pacific/Honolulu',  
            -11: 'Pacific/Midway',      
            -12: 'Pacific/Kwajalein'  
        }
        return timezone_dict.get(offset)
    
    def atlas_photometry(object_name, account, password, atlas_url):
        try:
            session_req = requests.Session()
            login_page_url = "https://star.pst.qub.ac.uk/sne/atlas4/userlist_quickview/44/"
            login_url = "https://star.pst.qub.ac.uk/sne/atlas4/accounts/auth/"
            next_s = "/sne/atlas4/userlist_quickview/44/"

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/91.0.4472.124 Safari/537.36"
            }

            login_page = session_req.get(login_page_url, headers=headers)
            login_soup = BeautifulSoup(login_page.content, "html.parser")
            csrf_input = login_soup.find("input", {"name": "csrfmiddlewaretoken"})
            csrf_token = csrf_input["value"] if csrf_input else ""

            login_data = {
                "username": account,
                "password": password,
                "csrfmiddlewaretoken": csrf_token,
                "next": next_s
            }
            headers["Referer"] = login_page_url
            login_response = session_req.post(login_url, data=login_data, headers=headers)
            if "authentication failed" in login_response.text.lower():
                return {"status": "error", "message": "登入失敗"}

            time.sleep(2)

            page = session_req.get(atlas_url, headers=headers)
            if page.status_code != 200:
                return {"status": "error", "message": "Can not get data"}
            if "login" in page.url.lower():
                return {"status": "error", "message": "Please check your username or password"}

            soup = BeautifulSoup(page.content, "html.parser")
            tables = []
            container_divs = soup.find_all(class_="table-container")
            for container in container_divs:
                tables_in_container = container.find_all("table")
                if tables_in_container:
                    tables.extend(tables_in_container)
            if not tables:
                tables = soup.find_all("table", class_="table-container")
            if not tables:
                return {"status": "error", "message": "Can not find data"}

            data_dict = {}
            for table in tables:
                header_row = table.find("tr")
                if not header_row:
                    continue
                headers_list = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
                try:
                    idx_mjd = headers_list.index("Mjd")
                    idx_mag = headers_list.index("Mag")
                    idx_dmag = headers_list.index("Dmag")
                    idx_filt = headers_list.index("Filt")
                except ValueError:
                    continue

                rows = table.find_all("tr")[1:]
                for row in rows:
                    cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                    if len(cols) < len(headers_list):
                        continue
                    mjd = cols[idx_mjd]
                    mag = cols[idx_mag]
                    dmag = cols[idx_dmag]
                    filt = cols[idx_filt]
                    line = f"{mjd} {mag} {dmag}"
                    data_dict.setdefault(filt, []).append(line)

            if not data_dict:
                return {"status": "error", "message": "No valid data"}

            upload_folder = os.path.join(base_upload_folder, object_name, 'Photometry')
            os.makedirs(upload_folder, exist_ok=True)
            for filt, lines in data_dict.items():
                filename = f"{object_name}_{filt}_photometry_ATLAS.txt"
                file_path = os.path.join(upload_folder, filename)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("\n".join(lines))

            return {"status": "success", "message": "ATLAS photometry uploaded successfully"}
        
        except Exception as e:
            return {"status": "error", "message": f"Error: {e}"}
