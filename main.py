# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
# IMPORTANT: DO NOT share PASSWORD publicly.
import os
import sqlite3
import uuid
import obsplanning as obs
import ephem
import re
import configparser

import matplotlib
matplotlib.use('Agg')

from flask import Flask, render_template, request, redirect, url_for, session, render_template_string, jsonify, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from datetime import datetime

from Run_python.User_control import UserManagement
from Run_python.data_processing import Data_Process
from Run_python.Trigger import Generate

app = Flask(__name__, static_folder="static")

app.secret_key = 'test'

config = configparser.ConfigParser()
config.read('config.ini')
BASE_DIR = config['Paths']['BASE_DIR']

USER_DATA_FILE = os.path.join(BASE_DIR, 'Other', 'users.txt')
PENDING_USER_FILE = os.path.join(BASE_DIR, 'Other', 'pending_users.txt')
RESET_TOKEN_FILE= os.path.join(BASE_DIR, 'Other', 'reset_tokens.txt')
COMMENTS = os.path.join(BASE_DIR, 'Other', 'comments.db') 

#base_upload_folder = os.path.join(BASE_DIR, 'Upload')  
base_upload_folder = os.path.join(BASE_DIR, 'Lab_Data') 
base_path = os.path.join(BASE_DIR, 'Data_img') 

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
# upload photometry
@app.route('/upload_photometry/<object_name>', methods=['POST'])
def upload_photometry(object_name):
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "No file part"})
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({"status": "error", "message": "No file selected"})

        if file and file.filename.endswith('.txt'): 
            upload_folder = os.path.join(base_upload_folder, object_name, 'Photometry')
            os.makedirs(upload_folder, exist_ok=True)

            filename, file_extension = os.path.splitext(file.filename)
            current_date = datetime.now().strftime("%Y_%m_%d")

            save_path = os.path.join(upload_folder, file.filename)
            counter = 1
            while os.path.exists(save_path):
                new_filename = f"{filename}_{current_date}_{counter}{file_extension}"
                save_path = os.path.join(upload_folder, new_filename)
                counter += 1
            file.save(save_path)
            return jsonify({"status": "success", "message": f"File successfully uploaded"})
        
        return jsonify({"status": "error", "message": "Invalid file format. Only .txt files are allowed."})

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
        # 處理表單提交
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
                target = {
                    'object_name': obj,
                    'ra': convert_ra_format(ra),
                    'dec': convert_dec_format(dec),
                }
                targets_all.append(target)
                observable_priority = Generate.observe_priority(ra)
                targets.append({'obj': obj, 'ra': ra, 'dec': dec, 'mag': mag, 'too': too, 'priority': observable_priority})
        
        targets.sort(key=lambda x: x['priority'])

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
    print(data)
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


# add comment =============================================================================
@app.route('/get_comments/<object_name>')
def get_comments(object_name):
    conn = sqlite3.connect(COMMENTS)
    cursor = conn.cursor()
    cursor.execute('SELECT username, comment, timestamp FROM comments WHERE object_name = ?', (object_name,))
    comments = cursor.fetchall()
    conn.close()

    # render html
    comments_html = render_template_string('''
        {% for comment in comments %}
            <div class="comment">
                <p><strong>{{ comment[0] }}:</strong> {{ comment[1] }}</p>
                <small>{{ comment[2] }}</small>
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
        Permission_list = object_info['Permission'].split(' & ')
        if object_info['Permission'] == 'public' or user_organization in Permission_list or user_organization == 'admin': 
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
                print(session)
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
import json
with open("token.json", "r") as file:
    tokens = json.load(file)
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
        
        name = f"{name}\nRA: {ra}\nDEC: {dec}"
        
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
    app.run(host='0.0.0.0', port=80)

#git add .
#git commit -m "XXX"
