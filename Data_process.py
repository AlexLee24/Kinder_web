import os
import numpy as np
import matplotlib.pyplot as plt
from astropy.io import fits

# PATH
DATA_TEST_PATH = 'A:\_Lab\Lab_web\Lab_Data'
DATA_TEST_PATH = os.path.normpath(DATA_TEST_PATH)


# stretch_image
def stretch_image(data, stretch_factor=0.1):
    # Calculate the mean and standard deviation to set clipping bounds
    mean = np.mean(data)
    std_dev = np.std(data)

    # Clip the data to the specified bounds and apply a non-linear stretch
    min_val = mean - stretch_factor * std_dev
    max_val = mean + stretch_factor * std_dev
    stretched_data = np.clip((data - min_val) / (max_val - min_val), 0, 1)  # Scale to range 0 to 1

    return stretched_data

# read fits
def extract_fits_image_and_info(fits_file, image_filename):
    hdu_list = fits.open(fits_file)
    image_data = hdu_list[0].data
    header = hdu_list[0].header
    ra = header.get('RA', 'N/A')
    dec = header.get('DEC', 'N/A')
    hdu_list.close()

    stretched_image = stretch_image(image_data, stretch_factor=3.0)
    
    height, width = stretched_image.shape
    center_x, center_y = width / 2, height / 2

    plt.figure(figsize=(6, 6))
    plt.imshow(stretched_image, cmap='gray', origin='lower', aspect='auto')
    plt.plot(center_x, center_y, 'o', color='red', markersize=30, markerfacecolor='none')  # Red circle outline
    plt.axis('off')
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    plt.savefig(image_filename)
    plt.close()

    return ra, dec


# Save object info as a text file
def save_object_info(data_output_folder, obj_name, ra, dec, photo_path):
    ra = ra.replace(' ', ':')
    dec = dec.replace(' ', ':')
    
    photo_path = os.path.normpath(photo_path)
    txt_name = f"{obj_name}_info.txt"
    info_filename = os.path.join(data_output_folder, txt_name)
    with open(info_filename, 'w') as f:
        f.write(f"Object_Name: {obj_name}\n")
        f.write(f"RA: {ra}\n")
        f.write(f"DEC: {dec}\n")
        f.write(f"Photo_path: {photo_path}\n")
        f.write(f"Transient_type: \n")
    return info_filename

def process_data_folders(data_folder ,data_path=DATA_TEST_PATH):
    txt_paths = [] 
    for obj_folder in os.listdir(data_path):
        if obj_folder == data_folder or data_folder == 0:
            obj_path = os.path.join(data_path, obj_folder)
            if os.path.isdir(obj_path):
                photo_folder = os.path.join(obj_path, 'Photo')          # photo folder
                spectrum_folder = os.path.join(obj_path, 'Spectrum')    # spectrum folder
                data_output_folder = os.path.join(obj_path, 'Data')     # final data folder
                
                photo_file = next((f for f in os.listdir(photo_folder) if f.endswith('.fits')), None)
                spectrum_file = next((f for f in os.listdir(spectrum_folder) if f.endswith('.dat')), None)

                if photo_file and spectrum_file:
                    photo_path = os.path.join(photo_folder, photo_file)
                    
                    photo_image_path = os.path.join(data_output_folder, f"{obj_folder}_photo.png")
                    
                    os.makedirs(data_output_folder, exist_ok=True)
                    
                    ra, dec = extract_fits_image_and_info(photo_path, photo_image_path)
                    
                    txt_path = save_object_info(data_output_folder, obj_folder, ra, dec, photo_image_path)
                    txt_paths.append(os.path.normpath(txt_path))
                
    return txt_paths

# RUN
if __name__ == "__main__":
    data_folder = 0  # 0 for all
    txt_paths = process_data_folders(data_folder)
    print("txt_path:", txt_paths)
