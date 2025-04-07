# Last update at: 2025-04-03
# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
# =================================================================================================
# =================================================================================================
# =================================================================================================
import os
import re
import sys
import time
import uuid
import ephem
import shutil
import sqlite3
import requests
import configparser


import matplotlib
matplotlib.use('Agg')

from bs4 import BeautifulSoup
from datetime import datetime
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, session, render_template_string, jsonify, flash, send_from_directory

import Run_python.new_obsplan as obs
from Run_python.Trigger import Generate
from Run_python.User_control import UserManagement
from Run_python.data_processing import Data_Process


app = Flask(__name__, static_folder="static")

app.secret_key = 'test'

config = configparser.ConfigParser()
config.read('config_file.ini')
BASE_DIR = config['Paths']['BASE_DIR']
debug_mode = config.getboolean('debug', 'DEBUG')

path_ex = os.path.exists(BASE_DIR)
if path_ex == False:
    print("=================== Check the path in config.ini file ===================")
    sys.exit()

USER_DATA_FILE = os.path.join(BASE_DIR, 'Other', 'users.txt')
PENDING_USER_FILE = os.path.join(BASE_DIR, 'Other', 'pending_users.txt')
RESET_TOKEN_FILE= os.path.join(BASE_DIR, 'Other', 'reset_tokens.txt')
COMMENTS = os.path.join(BASE_DIR, 'Other', 'comments.db') 

#base_upload_folder = os.path.join(BASE_DIR, 'Upload')  
base_upload_folder = os.path.join(BASE_DIR, 'Lab_Data') 
base_path = os.path.join(BASE_DIR, 'Data_img') 

import json
with open("token.json", "r") as file:
    tokens = json.load(file)
#================================ Define code ======================================
#================================ Define code ======================================
#================================ Define code ======================================
# comments
comments = []
def init_db():
    conn = sqlite3.connect(COMMENTS)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_name TEXT,
            username TEXT,
            comment TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

#==================================== route =================================================
#==================================== route =================================================
#==================================== route =================================================
@app.route('/upload_pessto/<object_name>', methods=['POST'])
def upload_pessto(object_name):
    data = request.get_json()
    account = data.get('account')
    password = data.get('password')

    if not account or not password:
        return jsonify({"status": "error", "message": "Please enter account and password"}), 400
    
    object_name_1 = object_name
    try:
        object_name = object_name.replace(' ', '')
    except Exception as e:
        object_name = object_name
    
    LOGIN_URL = "https://www.pessto.org/marshall/login"
    TARGET_URL = f"https://www.pessto.org/marshall/transients/search?q={object_name}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        session_req = requests.Session()
        login_page = session_req.get(LOGIN_URL, headers=headers)
        soup = BeautifulSoup(login_page.text, "html.parser")
        
        csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
        if not csrf_input:
            csrf_input = soup.find("input", {"name": "csrf_token"})
            csrf_input = csrf_input or soup.find("input", {"name": "_csrf_token"})
            csrf_input = csrf_input or soup.find("input", {"name": "_token"})
        csrf_token = csrf_input["value"] if csrf_input else ""
        
        login_data = {
            "login": account,
            "password": password
        }
        if csrf_token:
            login_data["csrfmiddlewaretoken"] = csrf_token

        headers["Referer"] = LOGIN_URL
        login_response = session_req.post(LOGIN_URL, data=login_data, headers=headers, allow_redirects=True)
        if login_response.status_code != 200:
            return jsonify({"status": "error", "message": "Login failed"}), 403

        time.sleep(2)
        target_response = session_req.get(TARGET_URL, headers=headers)
        if target_response.status_code != 200:
            return jsonify({"status": "error", "message": "Can not search this object"}), 404

        target_html = target_response.text
        soup = BeautifulSoup(target_html, "html.parser")
        tns_links = soup.find_all("a", href=lambda href: href and "wis-tns.org/object" in href)
        
        object_found = False
        match_element = None
        aka_data = []
        
        for link in tns_links:
            if link.get_text(strip=True) == object_name:
                object_found = True
                parent_row = link
                for _ in range(5):
                    if parent_row.parent:
                        parent_row = parent_row.parent
                        aka_list = parent_row.find("div", class_="row-fluid akaList")
                        if aka_list:
                            match_element = aka_list
                            break
                break
        
        if not object_found:
            for link in tns_links:
                parent_row = link
                parent_aka_list = None
                for _ in range(5):
                    if parent_row.parent:
                        parent_row = parent_row.parent
                        aka_list = parent_row.find("div", class_="row-fluid akaList")
                        if aka_list:
                            parent_aka_list = aka_list
                            break
                if parent_aka_list:
                    aka_links = parent_aka_list.find_all("a", href=True)
                    for aka_link in aka_links:
                        if aka_link.get_text(strip=True) == object_name:
                            object_found = True
                            match_element = parent_aka_list
                            break
                if object_found:
                    break

        if object_found and match_element:
            aka_links = match_element.find_all("a", href=True)
            results = []
            for aka_link in aka_links:
                name = aka_link.get_text(strip=True)
                link_url = aka_link["href"]
                aka_data.append({"name": name, "link": link_url})
                if name.startswith("ATLAS"):
                    pessto_account = tokens["PESSTO_USERNAME"]
                    pessto_password = tokens["PESSTO_PASSWORD"]
                    result = Data_Process.atlas_photometry(object_name_1, pessto_account, pessto_password, link_url)
                    results.append(result)
                elif name.startswith("ZTF"):
                    result = Data_Process.ztf_photometry(object_name_1, link_url)
                    results.append(result)
            
            return jsonify({
                "status": "success",
                "message": "All photometry processed successfully",
                "aka_data": aka_data,
                "results": results
            }), 200

        else:
            return jsonify({"status": "error", "message": "No object found in pessto", "data": aka_data})
    
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error: {e}"}), 500



@app.route('/upload_atlas_photometry/<object_name>', methods=['POST'])
def upload_atlas_photometry(object_name):
    data = request.get_json()
    account = data.get('account')
    password = data.get('password')
    atlas_url = data.get('atlas_url')
    
    if not account or not password or not atlas_url:
        return jsonify({"status": "error", "message": "請提供完整資訊"}), 400
    
    result = Data_Process.atlas_photometry(object_name, account, password, atlas_url)
    status_code = 200 if result.get("status") == "success" else 500
    return jsonify(result), status_code




# edit user org
@app.route('/admin_edit_user', methods=['GET', 'POST'])
def admin_edit_user():
    if 'username' not in session or session['username'] != 'admin':
        flash("Unauthorized access", "error")
        return redirect(url_for('login_page'))
    
    username = request.args.get('username')
    if not username:
        flash("No user specified", "error")
        return redirect(url_for('admin_dashboard'))
    
    user_data = UserManagement.get_user_data(username)
    if not user_data:
        flash("User not found.", "error")
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        new_organization = request.form.get('organization').strip()
        UserManagement.save_user_profile(username, user_data['first_name'], user_data['last_name'], user_data['email'], new_organization)
        flash("Organization updated successfully.", "success")
        return redirect(url_for('admin_dashboard'))
    
    return render_template('admin_edit_user.html', user=user_data)


# astronomy tools
@app.route('/astronomy_tools', methods=['GET'])
def astronomy_tools():
    return render_template('astronomy_tools.html')

# delete comment
@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    if 'username' not in session or session['username'] != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    try:
        conn = sqlite3.connect(COMMENTS)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM comments WHERE id = ?', (comment_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# add object
@app.route('/add_object', methods=['POST'])
def add_object():
    if 'username' not in session or session['username'] != 'admin':
        return redirect(url_for('login_page'))
    
    target_name = request.form.get('target_name')
    if not target_name:
        flash("Please enter an object name", "error")
        return redirect(url_for('object_list'))
    
    src = os.path.join(BASE_DIR, 'Other_Data', 'empty_object')
    dest = os.path.join(BASE_DIR, 'Lab_Data', target_name)
    
    if os.path.exists(dest):
        flash("Object with this name already exists.", "error")
        return redirect(url_for('object_list'))
    
    try:
        shutil.copytree(src, dest)
        data_folder = os.path.join(dest, 'Data')
        old_info_file = os.path.join(data_folder, 'object_name_info.txt')
        new_info_file = os.path.join(data_folder, f"{target_name}_info.txt")
        if os.path.exists(old_info_file):
            os.rename(old_info_file, new_info_file)
        flash("Object added successfully.", "success")
    except Exception as e:
        flash(f"Error adding object: {e}", "error")
    
    return redirect(url_for('object_list'))

# update_object_info
@app.route('/update_object_info/<object_name>', methods=['POST'])
def update_object_info(object_name):
    if 'username' not in session or session['username'] != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    data = request.get_json()
    new_ra = str(data.get('RA', None))
    new_dec = str(data.get('DEC', None))
    new_tntype = str(data.get('TNtype', None))
    new_permission = data.get('Permission', None)
    
    info_file = os.path.join(BASE_DIR, 'Lab_Data', object_name, 'Data', f"{object_name}_info.txt")
    if not os.path.exists(info_file):
        return jsonify({'success': False, 'message': 'Info file not found'}), 404

    try:
        with open(info_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        new_lines = []
        for line in lines:
            if line.startswith("RA:") and new_ra != "None":
                new_lines.append("RA: " + new_ra + "\n")
            elif line.startswith("DEC:") and new_dec != "None":
                new_lines.append("DEC: " + new_dec + "\n")
            elif line.startswith("Transient_type:") and new_tntype != "None":
                new_lines.append("Transient_type: " + new_tntype + "\n")
            elif line.startswith("Permission:") and new_permission != None:
                new_lines.append("Permission: " + new_permission + "\n")
            else:
                new_lines.append(line)
        
        with open(info_file, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# delete object
@app.route('/delete_object/<object_name>', methods=['POST'])
def delete_object(object_name):
    if 'username' not in session or session['username'] != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    src_lab_data = os.path.join(BASE_DIR, 'Lab_Data', object_name)
    delete_parent = os.path.join(BASE_DIR, 'Other_Data', 'delete_object')
    os.makedirs(delete_parent, exist_ok=True)
    
    temp_dest = os.path.join(delete_parent, object_name)
    data_img_folder = os.path.join(BASE_DIR, 'Data_img', object_name)

    try:
        if os.path.exists(src_lab_data):
            shutil.move(src_lab_data, temp_dest)
            deletion_time = datetime.now().strftime("%Y%m%d%H%M%S")
            new_dest = os.path.join(delete_parent, f"{object_name}_{deletion_time}")
            os.rename(temp_dest, new_dest)
        else:
            return jsonify({'success': False, 'message': 'Lab_Data folder not found'}), 404

        if os.path.exists(data_img_folder):
            shutil.rmtree(data_img_folder)

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# upload image
@app.route('/upload_object_photo/<object_name>', methods=['POST'])
def upload_object_photo(object_name):
    if 'username' not in session or session['username'] != 'admin':
        flash("Unauthorized access", "error")
        return redirect(url_for('login_page'))

    if 'photo' not in request.files:
        flash("No file part", "error")
        return redirect(url_for('object_data', object_name=object_name))
    
    photo_file = request.files['photo']
    if photo_file.filename == '':
        flash("No file selected", "error")
        return redirect(url_for('object_data', object_name=object_name))

    data_folder = os.path.join(BASE_DIR, 'Lab_Data', object_name, 'Data')
    if not os.path.exists(data_folder):
        flash("Data folder not found", "error")
        return redirect(url_for('object_data', object_name=object_name))

    original_filename = photo_file.filename
    extension = os.path.splitext(original_filename)[1]  # e.g. ".png" / ".jpg"
    new_filename = f"{object_name}_photo{extension}"
    save_path = os.path.join(data_folder, new_filename)

    try:
        photo_file.save(save_path)
    except Exception as e:
        flash(f"Error saving file: {e}", "error")
        return redirect(url_for('object_data', object_name=object_name))

    info_file = os.path.join(data_folder, f"{object_name}_info.txt")
    if not os.path.exists(info_file):
        flash("Info file not found to update photo path", "error")
        return redirect(url_for('object_data', object_name=object_name))
    
    try:
        with open(info_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        new_lines = []
        found_photo_path_line = False
        for line in lines:
            if line.startswith("Photo_path:"):
                new_lines.append(f"Photo_path: {new_filename}\n")
                found_photo_path_line = True
            else:
                new_lines.append(line)
        
        if not found_photo_path_line:
            new_lines.append(f"Photo_path: {new_filename}\n")

        with open(info_file, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)

        flash("Photo uploaded successfully.", "success")
    except Exception as e:
        flash(f"Error updating info.txt: {e}", "error")

    return redirect(url_for('object_data', object_name=object_name))

# edit object name
@app.route('/update_object_name_inline/<object_name>', methods=['POST'])
def update_object_name_inline(object_name):
    if 'username' not in session or session['username'] != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    data = request.get_json()
    new_name = data.get('newName', '').strip()
    if not new_name:
        return jsonify({'success': False, 'message': 'New object name cannot be empty.'}), 400

    old_folder = os.path.join(BASE_DIR, 'Lab_Data', object_name)
    new_folder = os.path.join(BASE_DIR, 'Lab_Data', new_name)

    if not os.path.exists(old_folder):
        return jsonify({'success': False, 'message': 'Original folder not found.'}), 404
    if os.path.exists(new_folder):
        return jsonify({'success': False, 'message': 'New folder already exists.'}), 400

    try:
        os.rename(old_folder, new_folder)
        for root, dirs, files in os.walk(new_folder):
            for file in files:
                if object_name in file:
                    old_file_path = os.path.join(root, file)
                    new_file_name = file.replace(object_name, new_name)
                    new_file_path = os.path.join(root, new_file_name)
                    os.rename(old_file_path, new_file_path)
        data_dir = os.path.join(new_folder, 'Data')
        info_file_path = os.path.join(data_dir, f"{new_name}_info.txt")
        if os.path.exists(info_file_path):
            with open(info_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                if line.startswith("Photo_path:"):
                    new_lines.append(f"Photo_path: {new_name}_photo.JPG\n")
                else:
                    new_lines.append(line)
            with open(info_file_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
        data_img_old_folder = os.path.join(BASE_DIR, 'Data_img', object_name)
        if os.path.exists(data_img_old_folder):
            shutil.rmtree(data_img_old_folder)
        return jsonify({'success': True, 'new_name': new_name})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# upload photometry
@app.route('/upload_photometry/<object_name>', methods=['POST'])
def upload_photometry(object_name):
    files = request.files.getlist('file')
    if not files or all(file.filename == '' for file in files):
        return jsonify({"status": "error", "message": "No file selected"})

    messages = []
    for file in files:
        if file.filename == '':
            continue
        if file and file.filename.endswith('.txt'):
            upload_folder = os.path.join(base_upload_folder, object_name, 'Photometry')
            os.makedirs(upload_folder, exist_ok=True)
            target_path = os.path.join(upload_folder, file.filename)
            
            if os.path.exists(target_path):
                try:
                    new_content = file.read().decode('utf-8')
                    new_lines = [line.strip() for line in new_content.splitlines() if line.strip()]
                    
                    with open(target_path, 'r', encoding='utf-8') as f:
                        existing_content = f.read()
                    old_lines = [line.strip() for line in existing_content.splitlines() if line.strip()]
                    
                    lines_to_append = [line for line in new_lines if line not in old_lines]
                    
                    if not lines_to_append:
                        messages.append(f"{file.filename}: Uploaded content is already present; nothing appended.")
                        continue
                    
                    with open(target_path, 'a', encoding='utf-8') as f:
                        for line in lines_to_append:
                            f.write("\n" + line)
                    messages.append(f"{file.filename}: File content appended successfully.")
                except Exception as e:
                    messages.append(f"{file.filename}: Error appending content: {e}")
            else:
                try:
                    file.save(target_path)
                    messages.append(f"{file.filename}: File successfully uploaded.")
                except Exception as e:
                    messages.append(f"{file.filename}: Error saving file: {e}")
        else:
            messages.append(f"{file.filename}: Invalid file format. Only .txt files are allowed.")
    
    if messages:
        return jsonify({"status": "success", "message": " ".join(messages)})
    else:
        return jsonify({"status": "error", "message": "No valid files processed."})




#Trigger 
def convert_ra_format(ra):
    parts = ra.split(':')
    if len(parts) == 3:
        hours = parts[0] + 'h'
        minutes = parts[1] + 'm'
        seconds = parts[2] + 's'
        return f"{hours} {minutes} {seconds}"
    else:
        raise ValueError("Invalid RA format. Expected format: xx:xx:xx")

def convert_dec_format(dec):
    parts = dec.split(':')
    if len(parts) == 3:
        degrees = parts[0] + 'd'
        minutes = parts[1] + 'm'
        seconds = parts[2] + 's'
        return f"{degrees} {minutes} {seconds}"
    else:
        raise ValueError("Invalid DEC format. Expected format: xx:xx:xx")

@app.route('/trigger', methods=['GET', 'POST'])
def trigger_view():
    plot_folder = os.path.join(app.root_path, "static", "ov_plot")
    if request.method == 'POST':
        targets = []
        targets_all = []
        for key in request.form.keys():
            if key.startswith('obj-'):
                index = key.split('-')[1]
                obj = request.form[f'obj-{index}']
                ra = request.form[f'ra-{index}']
                dec = request.form[f'dec-{index}']
                mag = request.form[f'mag-{index}']
                too = 'yes' if f'too-{index}' in request.form else 'no'
                observable_priority = Generate.observe_priority(ra)
                targets.append({'obj': obj, 'ra': ra, 'dec': dec, 'mag': mag, 'too': too, 'priority': observable_priority})
        
        targets.sort(key=lambda x: x['priority'])
        
        for i in targets:
            obj = i['obj']
            ra = i['ra']
            dec = i['dec']
            try:
                target = {
                    'object_name': obj,
                    'ra': convert_ra_format(ra),
                    'dec': convert_dec_format(dec),
                }
                targets_all.append(target)
            except ValueError as e:
                return redirect(url_for('trigger_view'))
        
        messages = []
        for target in targets:
            ToO = target['too'] == 'yes'
            message = Generate.generate_message(target['obj'], target['ra'], target['dec'], target['mag'], ToO)
            messages.append(message)
            
        unique_filename = Generate.generate_plot(targets_all, plot_folder)

        return jsonify({
            'messages': messages,
            'targets_all': targets_all,
            'success': True,
            'plot_url': f"/static/ov_plot/{unique_filename}"
        })
    return render_template('trigger.html')

# admin to clear all comments
@app.route('/clear_comments', methods=['POST'])
def clear_comments():
    if 'username' not in session or session['username'] != 'admin':
        return redirect(url_for('login_page'))
    
    try:
        conn = sqlite3.connect(COMMENTS)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM comments') 
        conn.commit()
        conn.close()
        flash("All comments have been cleared.", "success")
    except Exception as e:
        flash(f"Error clearing comments: {e}", "error")
    
    return redirect(url_for('admin_dashboard'))


@app.route('/Data_img/<path:filename>')
def serve_data_img(filename):
    return send_from_directory(base_path, filename)

# Save data route
@app.route('/save_data', methods=['POST'])
def save_data_route():
    data = request.json.get('data', [])
    Data_Process.save_data(data)
    return jsonify({"status": "success"})

# Direct page
@app.route('/')
def home():
    return render_template('index.html', current_path='/')


@app.route('/object_list.html')
def object_list():
    search_query = request.args.get('search', '').lower()
    objects = Data_Process.scan_data_folders()
    if search_query:
        objects = [obj for obj in objects if search_query in obj['object_name'].lower()]
    else:
        objects = Data_Process.scan_data_folders()
        
    return render_template('object_list.html', objects=objects)


# admin file management ====================================================================
@app.route('/admin_file_manager', methods=['GET'])
def admin_file_manager():
    if 'username' not in session or session['username'] != 'admin':
        flash("Unauthorized access", "error")
        return redirect(url_for('login_page'))
    
    rel_path = request.args.get('path', '')
    abs_path = os.path.abspath(os.path.join(BASE_DIR, rel_path))
    
    if not abs_path.startswith(BASE_DIR):
        flash("Access denied", "error")
        return redirect(url_for('admin_file_manager'))
    
    items = os.listdir(abs_path)
    file_items = []
    for item in items:
        if item == '.DS_Store':
            continue
        item_abs = os.path.join(abs_path, item)
        file_items.append({
            'name': item,
            'is_dir': os.path.isdir(item_abs),
            'rel_path': os.path.join(rel_path, item).replace("\\", "/")  
        })
    
    return render_template('admin_file_manager.html', current_path=rel_path, items=file_items)

@app.route('/admin_file_manager/edit', methods=['GET', 'POST'])
def admin_file_edit():
    if 'username' not in session or session['username'] != 'admin':
        flash("Unauthorized access", "error")
        return redirect(url_for('login_page'))
    
    file_rel_path = request.args.get('path')
    if not file_rel_path:
        flash("No file specified", "error")
        return redirect(url_for('admin_file_manager'))
    abs_file_path = os.path.abspath(os.path.join(BASE_DIR, file_rel_path))
    if not abs_file_path.startswith(BASE_DIR):
        flash("Access denied", "error")
        return redirect(url_for('admin_file_manager'))
    
    if request.method == 'POST':
        content = request.form.get('content')
        try:
            with open(abs_file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            flash("File saved successfully", "success")
        except Exception as e:
            flash(f"Error saving file: {e}", "error")
        return redirect(url_for('admin_file_manager', path=os.path.dirname(file_rel_path)))
    
    try:
        with open(abs_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        flash(f"Error opening file: {e}", "error")
        return redirect(url_for('admin_file_manager', path=os.path.dirname(file_rel_path)))
    
    return render_template('admin_file_edit.html', file_path=file_rel_path, content=content)

@app.route('/admin_file_manager/delete', methods=['POST'])
def admin_file_delete():
    if 'username' not in session or session['username'] != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    file_rel_path = request.form.get('path')
    abs_file_path = os.path.abspath(os.path.join(BASE_DIR, file_rel_path))
    if not abs_file_path.startswith(BASE_DIR):
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    try:
        os.remove(abs_file_path)
        flash("File deleted successfully", "success")
        return redirect(url_for('admin_file_manager', path=os.path.dirname(file_rel_path)))
    except Exception as e:
        flash(f"Error deleting file: {e}", "error")
        return redirect(url_for('admin_file_manager', path=os.path.dirname(file_rel_path)))

@app.route('/admin_file_manager/new', methods=['GET', 'POST'])
def admin_file_new():
    if 'username' not in session or session['username'] != 'admin':
        flash("Unauthorized access", "error")
        return redirect(url_for('login_page'))
    
    current_rel_path = request.args.get('path', '')
    abs_dir_path = os.path.abspath(os.path.join(BASE_DIR, current_rel_path))
    if not abs_dir_path.startswith(BASE_DIR):
        flash("Access denied", "error")
        return redirect(url_for('admin_file_manager'))
    
    if request.method == 'POST':
        filename = request.form.get('filename')
        content = request.form.get('content', '')
        
        if not filename.endswith('.txt'):
            filename += '.txt'
        
        new_file_path = os.path.join(abs_dir_path, filename)
        try:
            with open(new_file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            flash("File created successfully", "success")
        except Exception as e:
            flash(f"Error creating file: {e}", "error")
        return redirect(url_for('admin_file_manager', path=current_rel_path))
    
    return render_template('admin_file_new.html', current_path=current_rel_path)



# add comment =============================================================================
@app.route('/get_comments/<object_name>')
def get_comments(object_name):
    conn = sqlite3.connect(COMMENTS)
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, comment, timestamp FROM comments WHERE object_name = ?', (object_name,))
    comments = cursor.fetchall()
    conn.close()

    # render html
    comments_html = render_template_string('''
    {% for comment in comments %}
    <div class="comment" data-id="{{ comment[0] }}">
        <p>
            <strong>{{ comment[1] }}:</strong> {{ comment[2] }}
            {% if session.get('username') == 'admin' %}
                <button onclick="deleteComment({{ comment[0] }})" class="delete-comment-button">Delete</button>
            {% endif %}
        </p>
        <small>{{ comment[3] }}</small>
    </div>
    {% endfor %}
''', comments=comments)

    return jsonify({"comments_html": comments_html})


@app.route('/comments/<object_name>', methods=['POST'])
def add_comment(object_name):
    username = session.get('username')
    comment = request.json.get('comment')
    
    if not username:
        return jsonify({"success": False}), 403

    # save comment
    conn = sqlite3.connect(COMMENTS)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO comments (object_name, username, comment) VALUES (?, ?, ?)', (object_name, username, comment))
    conn.commit()

    # update comment
    cursor.execute('SELECT username, comment, timestamp FROM comments WHERE object_name = ?', (object_name,))
    comments = cursor.fetchall()
    conn.close()

    # render html
    comments_html = render_template_string('''
        {% for comment in comments %}
            <p><strong>{{ comment[0] }}:</strong> {{ comment[1] }}</p>
            <small>{{ comment[2] }}</small>
        {% endfor %}
    ''', comments=comments)

    return jsonify({"success": True, "comments_html": comments_html})



# add comment END=============================================================================
# add comment END=============================================================================
# add comment END=============================================================================

# Route to display individual object data
@app.route('/object_data/<object_name>')
def object_data(object_name):
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    objects = Data_Process.scan_data_folders()
    object_info = next((obj for obj in objects if obj['object_name'] == object_name), None)
    user_organization = session.get('organization')
    
    if object_info:
        permission = object_info['Permission']
        Permission_list = permission.split(' & ')
        if permission == 'public' or permission == 'Public' or user_organization in Permission_list or user_organization == 'admin':
            conn = sqlite3.connect(COMMENTS)
            cursor = conn.cursor()
            cursor.execute('SELECT username, comment, timestamp FROM comments WHERE object_name = ?', (object_name,))
            comments = cursor.fetchall()
            conn.close()
            return render_template('object_data_temp.html', **object_info)
        else:
            return render_template('No_permission.html', current_path='/aboutus.html')

    else:
        return "Object not found", 404


@app.route('/observation.html')
def observation():
    data = Data_Process.load_data() # Load observation data
    return render_template('observation.html', data=data, current_path='/observation.html')


@app.route('/aboutus.html')
def aboutus():
    return render_template('aboutus.html', current_path='/aboutus.html')


@app.route('/object_plot.html')
def object_plot():
    return render_template('object_plot.html', current_path='/object_plot.html')


# Login 
@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        with open(PENDING_USER_FILE, 'r') as f:
            pending_users = [line.split(',')[0] for line in f.readlines()]
        
        if username in pending_users:
            return redirect(url_for('login_page', error='pending'))

        users, ueres_org = UserManagement.load_users() 
        hashed_password = users.get(username)
        org = ueres_org.get(username)
        
        if hashed_password:
            password_check = check_password_hash(hashed_password, password)
            if password_check:
                session['username'] = username
                session['organization'] = org
                next_page = request.args.get('next', url_for('home'))
                return redirect(next_page)
        return redirect(url_for('login_page', error=1))

    error = request.args.get('error')
    return render_template('login.html', current_path='/login', error=error)


# object_data_temp
@app.route('/object_data_temp.html')
def object_data_temp():
    return render_template('object_data_temp.html')


# Logout
@app.route('/logout')
def logout():
    session.pop('username', None)
    next_page = request.args.get('next', url_for('home'))
    return redirect(next_page)

# register ================================================================================
# register ================================================================================
# register ================================================================================

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = tokens["MAIL_USERNAME"]
app.config['MAIL_PASSWORD'] = tokens["MAIL_PASSWORD"]

mail = Mail(app)

def add_pending_user(username, first_name, last_name, email, password, organization):
    verification_code = str(uuid.uuid4())  
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')  
    with open(PENDING_USER_FILE, 'a') as f:
        f.write(f"{username},{hashed_password},{first_name},{last_name},{email},{organization},{verification_code},0\n")
    
    return verification_code


# send notification email
def send_notification_email(to_email, subject, body):
    msg = Message(subject, sender=tokens["MAIL_USERNAME"],  recipients=[to_email])
    msg.body = body
    mail.send(msg)


def delete_user(username):
    lines = []
    user_deleted = False  

    with open(PENDING_USER_FILE, 'r') as f:
        lines = f.readlines()

    with open(PENDING_USER_FILE, 'w') as f:
        for line in lines:
            first_field = line.split(',')[0]
            if first_field == username:
                user_deleted = True 
                continue  
            f.write(line)


def is_user_registered(username, email):
    try:
        with open(USER_DATA_FILE, 'r') as f:
            for line in f:
                fields = line.strip().split(',')
                if fields[0] == username or fields[4] == email:
                    return True  
    except FileNotFoundError:
        pass
    return False


def is_user_pending(username, email):
    try:
        with open(PENDING_USER_FILE, 'r') as f:
            for line in f:
                fields = line.strip().split(',')
                if fields[0] == username and fields[4] == email:
                    return True  
                elif fields[0] == username or fields[4] == email:
                    return True  
    except FileNotFoundError:
        pass
    return False


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        organization = request.form['organization']
        
        if username == 'admin':
            flash("You can not use admin as username.", "error")
            return render_template('register.html', first_name=first_name, last_name=last_name, email=email, organization=organization)
        
        if is_user_registered(username, email):
            flash("The username or email is already registered.", "error")
            return render_template('register.html', first_name=first_name, last_name=last_name, organization=organization)

        if is_user_pending(username, email):
            flash("The username or email is already pending approval.", "warning")
            return render_template('register.html', first_name=first_name, last_name=last_name, organization=organization)
        
        if password != confirm_password:
            flash("Passwords do not match", "error")
            return render_template('register.html', username=username, first_name=first_name, last_name=last_name, email=email, organization=organization)
        
        if len(password) < 8:
            flash("Passwords is too short", "error")
            return render_template('register.html', username=username, first_name=first_name, last_name=last_name, email=email, organization=organization)
        
        if not re.search(r'[a-zA-Z]', password):
            flash("Password must contain at least one English letter", "error")
            return render_template('register.html', username=username, first_name=first_name, last_name=last_name, email=email, organization=organization)
        
        
        add_pending_user(username, first_name, last_name, email, password, organization)
        
        # send reg email
        send_notification_email(email, "Registration Received", 
            f"Dear {first_name} ({username}),\n\nThank you for registering. Your account is pending approval by an admin. You will receive another email once your account is approved.\n\nBest regards,\nGREAT Lab Team")
        
        return redirect(url_for('register_success'))  
    return render_template('register.html')


# approve
@app.route('/approve_user', methods=['POST'])
def approve_user():
    if session.get('username') != 'admin':
        return redirect(url_for('login'))

    username = request.form['username']
    lines = []
    approved_user_line = None
    
    with open(PENDING_USER_FILE, 'r') as f:
        for line in f:
            if line.startswith(f"{username},"): 
                approved_user_line = line.strip() 
            else:
                lines.append(line)

    if approved_user_line:
        with open(PENDING_USER_FILE, 'w') as f:
            f.writelines(lines)
        
        # pending to user
        parts = approved_user_line.split(',')
        with open(USER_DATA_FILE, 'a') as user_file:
            user_file.write(f"{parts[0]},{parts[1]},{parts[2]},{parts[3]},{parts[4]},{parts[5]},1\n")

        # send active email
        send_notification_email(
            parts[4], 
            "Account Approved", 
            f"Dear {parts[2]} ({parts[0]}),\n\nYour account has been approved and is now active. You can log in using your username and password.\n\nBest regards,\nGREAT Lab"
        )
    return redirect(url_for('admin_dashboard'))


@app.route('/reject_user', methods=['POST'])
def reject_user():
    if session.get('username') != 'admin':
        return redirect(url_for('login'))

    username = request.form['username']
    delete_user(username) 

    return redirect(url_for('admin_dashboard'))


# admin dash
@app.route('/admin_dashboard')
def admin_dashboard():
    if session.get('username') != 'admin':
        return redirect(url_for('login_page'))

    # load pending
    pending_users = []
    with open(PENDING_USER_FILE, 'r') as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) == 8 and parts[7] == '0':  
                pending_users.append({
                    'username': parts[0],
                    'first_name': parts[2],
                    'last_name': parts[3],
                    'email': parts[4],
                    'organization': parts[5]
                })
    
    exist_users = []
    with open(USER_DATA_FILE, 'r') as f:
        for line in f:
            parts = line.strip().split(',')
            exist_users.append({
                'username': parts[0],
                'first_name': parts[2],
                'last_name': parts[3],
                'email': parts[4],
                'organization': parts[5]
            })
    return render_template('admin_dashboard.html', pending_users=pending_users, exist_users=exist_users)


@app.route('/register_success')
def register_success():
    return render_template('register_success.html')


# Reset password
def email_exists(email):
    with open(USER_DATA_FILE, 'r') as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) > 4 and parts[4] == email:  
                return True
    return False


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        if not email_exists(email):
            return redirect(url_for('forgot_password', error=2))
        token = str(uuid.uuid4())  
        
        # save token with mail
        with open(RESET_TOKEN_FILE, 'a') as f:
            f.write(f"{email},{token}\n")
        
        # build reset url
        reset_url = url_for('reset_password', token=token, _external=True)
        
        # send reset email
        send_notification_email(email, "Password Reset Request", f"Click the link to reset your password: {reset_url}")
        
        return redirect(url_for('forgot_password_confirmation'))
    
    error = request.args.get('error')
    return render_template('forgot_password.html', error=error)


@app.route('/forgot_password_confirmation')
def forgot_password_confirmation():
    return render_template('forgot_password_confirmation.html')


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    email = None
    with open(RESET_TOKEN_FILE, 'r') as f:
        lines = f.readlines()
        for line in lines:
            saved_email, saved_token = line.strip().split(',')
            if saved_token == token:
                email = saved_email
                break
    
    # if no token, back to login
    if not email:
        flash("Invalid or expired reset token", "error")
        return redirect(url_for('login_page'))

    if request.method == 'POST':
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash("Passwords do not match", "error")
            return redirect(url_for('reset_password', token=token))

        # update password
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        lines_to_keep = []
        with open(USER_DATA_FILE, 'r') as f:
            for line in f:
                parts = line.strip().split(',')
                if parts[4] == email:
                    parts[1] = hashed_password
                    line = ','.join(parts) + '\n'
                lines_to_keep.append(line)

        # update users.txt
        with open(USER_DATA_FILE, 'w') as f:
            f.writelines(lines_to_keep)

        # remove token
        with open(RESET_TOKEN_FILE, 'w') as f:
            f.writelines([line for line in lines if saved_token != token])

        return redirect(url_for('login_page'))

    return render_template('reset_password.html', token=token)

# register END================================================================================
# user progfile
@app.route('/user_profile', methods=['GET', 'POST'])
def user_profile():
    if 'username' not in session:
        return redirect(url_for('login_page'))

    username = session['username']
    user_data = UserManagement.get_user_data(username) 

    return render_template('user_profile.html', **user_data)


@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'username' not in session:
        return redirect(url_for('login_page'))

    username = request.form.get('username')
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    email = request.form.get('email')
    organization = request.form.get('organization')

    UserManagement.save_user_profile(username, first_name, last_name, email, organization)
    flash("Profile updated successfully", "success")
    return redirect(url_for('user_profile'))


@app.route('/change_password', methods=['POST'])
def change_password():
    if 'username' not in session:
        return redirect(url_for('login_page'))

    username = session['username']
    current_password = request.form['current_password']
    new_password = request.form['new_password']
    confirm_new_password = request.form['confirm_new_password']

    if new_password == confirm_new_password:
        if UserManagement.verify_password(username, current_password):  
            UserManagement.update_password(username, new_password) 
            flash("Password changed successfully", "success")
        else:
            flash("Current password is incorrect", "error")
    else:
        flash("New passwords do not match", "error")

    return redirect(url_for('user_profile'))


@app.route('/example')
def example():
    flash("This is a success message", "success")
    flash("This is a error message", "error")
    flash("This is a info message", "info")
    flash("This is a warning message", "warning")
    return redirect(url_for('home'))


# generate object visibility for observation
@app.route("/generate_plot", methods=["POST"])
def generate_plot():
    data = request.get_json()
    object_name = data.get("object")
    ra = data.get("ra")
    dec = data.get("dec")
    
    ra = re.sub(r"[hH]", ":", ra)
    ra = re.sub(r"[mM]", ":", ra)
    ra = re.sub(r"[sS]", "", ra).strip()

    dec = re.sub(r"[dD°]", ":", dec)
    dec = re.sub(r"[mM′']", ":", dec)
    dec = re.sub(r"[sS″\"]", "", dec).strip()
    
    date = data.get("date")
    obs_date_int = str(int(date))
    next_obs_date_int = str(int(date) + 1)
    
    obs_date = f"{obs_date_int[:4]}/{obs_date_int[4:6]}/{obs_date_int[6:]}"
    next_obs_date = f"{next_obs_date_int[:4]}/{next_obs_date_int[4:6]}/{next_obs_date_int[6:]}"

    # LULIN'
    lulin_obs = obs.create_ephem_observer('Lulin Observatory', '120:52:21.5', '23:28:10.0', 2800)
    sunset, twi_civil, twi_naut, twi_astro = obs.calculate_twilight_times(lulin_obs,
    '2024/01/01 23:59:00')
    
    object_name_show = f"{object_name}\nRA: {ra}\nDEC: {dec}"
    target = obs.create_ephem_target(object_name_show, ra, dec)
    
    obs_start = ephem.Date(f'{obs_date} 17:00:00')
    obs_end = ephem.Date(f'{next_obs_date} 09:00:00')
    
    obs_start_local_dt = obs.dt_naive_to_dt_aware(obs_start.datetime(), 'Asia/Taipei')
    obs_end_local_dt = obs.dt_naive_to_dt_aware(obs_end.datetime(), 'Asia/Taipei')
    
    # Generate image
    plot_path = os.path.join("static", f"ov_plot\observing_tracks.jpg")

    obs.plot_night_observing_tracks(
        [target], lulin_obs, obs_start_local_dt, obs_end_local_dt, simpletracks=True, toptime='local',
        timezone='calculate', n_steps=1000, savepath=plot_path
    )
    
    return jsonify({"success": True, "plot_url": f"/{plot_path}"})


# for web
def enforce_max_files(folder, max_files):
    files = [os.path.join(folder, f) for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    if len(files) > max_files:
        files.sort(key=os.path.getmtime)  
        files_to_delete = files[:len(files) - max_files]
        for file_path in files_to_delete:
            os.remove(file_path)

@app.route("/generate_plot_2", methods=["POST"])
def generate_plot_2():
    target_list = []
    plot_folder = os.path.join(app.root_path, "static", "ov_plot")
    unique_filename = f"observing_tracks_{uuid.uuid4().hex}.jpg"
    enforce_max_files(plot_folder, max_files=10)
    
    data = request.get_json()
    date = data.get("date")
    observer = data.get("telescope")
    location = data.get("location")
    timezone = data.get("timezone")
    targets = data.get("targets")   #list
    
    date = date.replace("-","")
    timezone = Data_Process.get_timezone_name(int(timezone))
    for i in targets:
        name = i['object_name']
        ra = i['ra']
        dec = i['dec']
        
        ra = re.sub(r"[hH]", ":", ra)
        ra = re.sub(r"[mM]", ":", ra)
        ra = re.sub(r"[sS]", "", ra).strip()

        dec = re.sub(r"[dD°]", ":", dec)
        dec = re.sub(r"[mM′']", ":", dec)
        dec = re.sub(r"[sS″\"]", "", dec).strip()
        
        name = f"{name}"
        
        ephem_target = obs.create_ephem_target(name, ra, dec)
        target_list.append(ephem_target)
    
    if observer == None:
        longitude, latitude, altitude = location.split()
        obs_site = obs.create_ephem_observer('Observer', longitude, latitude, altitude)
    else:
        longitude, latitude, altitude = location.split()
        obs_site = obs.create_ephem_observer(obs, longitude, latitude, int(altitude))
    
    if date == None:
        flash("This is a success message", "success")
        
    obs_date = str(int(date))
    next_obs_date = str(int(date) + 1)
    
    obs_date = f"{obs_date[:4]}/{obs_date[4:6]}/{obs_date[6:]}"
    next_obs_date = f"{next_obs_date[:4]}/{next_obs_date[4:6]}/{next_obs_date[6:]}"
    
    obs_start = ephem.Date(f'{obs_date} 17:00:00')
    obs_end = ephem.Date(f'{next_obs_date} 09:00:00')
    
    obs_start_local_dt = obs.dt_naive_to_dt_aware(obs_start.datetime(), timezone)
    obs_end_local_dt = obs.dt_naive_to_dt_aware(obs_end.datetime(), timezone)
    
    plot_path = os.path.join(plot_folder, unique_filename)
    
    obs.plot_night_observing_tracks(
        target_list, obs_site, obs_start_local_dt, obs_end_local_dt, simpletracks=True, toptime='local',
        timezone='calculate', n_steps=1000, savepath=plot_path
    )
    
    return jsonify({"success": True, "plot_url": f"/static/ov_plot/{unique_filename}"})



# run
if __name__ == '__main__':
    #app.run(debug=True)
    app.run(host='0.0.0.0', port=80, debug=debug_mode)

#git add .
#git commit -m "XXX"
