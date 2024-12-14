import os
import numpy as np
import datetime
import shutil
import csv
from plotly import graph_objs as go

#BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = 'H:\\'
DATA_PATH = os.path.join(BASE_DIR, 'Lab_Data')
DATA_FILE = 'observations.csv'

#STATIC_IMAGE_FOLDER = '/static/data_images'
STATIC_IMAGE_FOLDER = '/Data_img'

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
def create_interactive_photometry_plot(photometry_file, plot_filename):
    data = np.loadtxt(photometry_file, usecols=(0, 1))
    time, mag = data[:, 0], data[:, 1]

    trace = go.Scatter(x=time, y=mag, mode='markers', name='Photometry')
    layout = go.Layout(
        title="Spectra",
        xaxis=dict(title="Time (JD)"),
        yaxis=dict(title="Mag"),
        template="seaborn"
    )
    fig = go.Figure(data=[trace], layout=layout)

    # Save the interactive plot as an HTML file
    fig.write_html(plot_filename)

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
            spectrum_path = os.path.join(data_path, obj_folder, "Spectrum", f"{obj_folder}_spectrum.dat")
            photometry_path = os.path.join(data_path, obj_folder, "Photometry", f"{obj_folder}_photometry.txt")

            if os.path.exists(txt_file_path) and os.path.exists(spectrum_path):
                last_update_date = datetime.datetime.fromtimestamp(os.path.getmtime(txt_file_path)).strftime('%Y-%m-%d %H:%M:%S')

                with open(txt_file_path, 'r') as file:
                    lines = file.readlines()
                    object_name = lines[0].split(": ")[1].strip()
                    ra = lines[1].split(": ")[1].strip()
                    dec = lines[2].split(": ")[1].strip()
                    photo_image_path = os.path.normpath(os.path.join(obj_path, lines[3].split(": ")[1].strip()))
                    TNtype = lines[4].split(": ")[1].strip() 
                    # create static
                    object_static_folder = os.path.join(STATIC_IMAGE_FOLDER, obj_folder)
                    os.makedirs(object_static_folder, exist_ok=True)

                    # copy fit to static
                    photo_dest = os.path.join(object_static_folder, f"{obj_folder}_photo.png")
                    shutil.copy(photo_image_path, photo_dest)

                    # create interactive plot
                    spectrum_html_path = os.path.join(object_static_folder, f"{obj_folder}_spectrum.html")
                    create_interactive_spectrum_plot(spectrum_path, spectrum_html_path)
                    
                    photometry_html_path = os.path.join(object_static_folder, f"{obj_folder}_photometry.html")
                    create_interactive_photometry_plot(photometry_path, photometry_html_path)
                    
                    # web_for_fit
                    web_photo_path = f"{photo_dest.replace(os.path.sep, '/')}"
                    web_spectrum_html_path = f"{spectrum_html_path.replace(os.path.sep, '/')}"
                    web_photometry_html_path = f"{photometry_html_path.replace(os.path.sep, '/')}"

                    print('web_photo_path',web_photo_path)
                    
                    # analyze dat
                    dat_file = next((f for f in os.listdir(os.path.join(data_path, obj_folder, "Spectrum")) if f.endswith('.dat')), None)
                    if dat_file:
                        dat_file_path = os.path.join(data_path, obj_folder, "Spectrum", dat_file)
                        dat_dest = os.path.join(object_static_folder, f"{obj_folder}_spectrum.dat")
                        shutil.copy(dat_file_path, dat_dest)
                        web_dat_path = f"/{dat_dest.replace(os.path.sep, '/')}"

                    else:
                        web_dat_path = None
                    
                    objects.append({
                        'object_name': object_name,
                        'RA': ra,
                        'DEC': dec,
                        'last_update_date': last_update_date,
                        'photo_image': web_photo_path,
                        'spectrum_html': web_spectrum_html_path,
                        'photometry_html': web_photometry_html_path,
                        'dat_file': web_dat_path,
                        'TNtype': TNtype
                    })
            else:
                print('='*50)
                print(f"Missing info.txt or spectrum file for {obj_folder}")
                print('='*50)

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