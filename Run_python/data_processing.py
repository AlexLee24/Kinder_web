import os
import numpy as np
import datetime
import shutil
import csv
import plotly.graph_objects as go
import configparser
import random

config = configparser.ConfigParser()
config.read('config.ini')
BASE_DIR = config['Paths']['BASE_DIR']

DATA_PATH = os.path.join(BASE_DIR, 'Lab_Data')
DATA_FILE = os.path.join(BASE_DIR,'Other', 'observations.csv')

STATIC_IMAGE_FOLDER = '/Data_img'
STATIC_IMAGE_FOLDER_Direct = os.path.join(BASE_DIR, 'Data_img')

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
def create_interactive_photometry_plot(photometry_files, plot_filename):
    traces = []
    filter_colors = {
        # 紫外線濾鏡
        'uvw2': '#6A5ACD',  # 淡紫色 (類似 UVW2)
        'uvm2': '#8470FF',  # 淡紫藍色 (類似 UVM2)
        'unw1': '#7B68EE',  # 紫藍色 (類似 UVW1)
        
        # 光學濾鏡
        'u': '#4B0082',    # 深紫色 (u band)
        'B': '#0000FF',    # 藍色 (B band)
        'g': '#2ca470',    # 綠色 (g band)
        'V': '#228B22',    # 深綠色 (V band)
        'r': '#FF0000',    # 紅色 (r band)
        'o': '#FFA500',    # 橙色 (o band)
        'i': '#FF69B4',    # 粉紅色 (i band)
        'z': '#8B0000',    # 深紅色 (z band)
        'y': '#D2691E',    # 棕橘色 (y band)
        'w': '#2E8B57',    # 海綠色 (w band)
        'c': '#8A2BE2',    # 藍紫色 (c band)

        # 紅外線濾鏡
        'J': '#8B4513',    # 棕色 (J band)
        'H': '#A0522D',    # 土紅色 (H band)
        'Ks': '#CD853F',   # 黃土色 (Ks band)
    }

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
            indices = [i for i, t in enumerate(data['telescope']) if t == telescope]
            trace = go.Scatter(
                x=[data['time'][i] for i in indices],
                y=[data['mag'][i] for i in indices],
                mode='markers',
                name=f'Filter: {filter_name} (Telescope: {telescope})',
                marker=dict(
                    color=filter_colors.get(filter_name, '#000000'),
                    symbol=marker_symbols[telescope],
                    size=10
                ),
                error_y=dict(
                    type='data',
                    array=[abs(data['error'][i]) for i in indices],
                    visible=True
                ),
                visible=True
            )
            traces.append(trace)
    
    layout = go.Layout(
        title="Photometry - Multiple Filters by clicking on the chart legend.",
        xaxis=dict(title="Time (MJD)", tickformat="d"),
        yaxis=dict(title="Magnitude", autorange="reversed"),
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
            obj = f"{obj_part[0]}{obj_part[1]}"
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
                    object_name = lines[0].split(": ")[1].strip()
                    ra = lines[1].split(": ")[1].strip()
                    dec = lines[2].split(": ")[1].strip()
                    photo_image_path = os.path.normpath(os.path.join(obj_path, lines[3].split(": ")[1].strip()))
                    TNtype = lines[4].split(": ")[1].strip() 
                    permission = lines[5].split(": ")[1].strip()
                    
                    # create static
                    object_static_folder = os.path.join(STATIC_IMAGE_FOLDER, obj_folder)
                    object_static_folder_direct = os.path.join(STATIC_IMAGE_FOLDER_Direct, obj_folder)
                    os.makedirs(object_static_folder_direct, exist_ok=True)

                    # copy fit to static
                    photo_dest = os.path.join(object_static_folder, f"{obj_folder}_photo.png")
                    photo_dest_dir = os.path.join(object_static_folder_direct, f"{obj_folder}_photo.png")
                    
                    if os.path.exists(photo_image_path):
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
                        'object_name': object_name,
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