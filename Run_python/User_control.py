import os
from werkzeug.security import generate_password_hash, check_password_hash
import configparser

class UserManagement: 
    config = configparser.ConfigParser()
    config.read('config.ini')
    BASE_DIR = config['Paths']['BASE_DIR']
    
    USER_DATA_FILE = os.path.join(BASE_DIR, 'Other', 'users.txt')
    PENDING_USER_FILE = os.path.join(BASE_DIR, 'Other', 'pending_users.txt')

    # Loading user
    def load_users(filename=USER_DATA_FILE):
        users = {}
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split(',')
                    if len(parts) >= 2:
                        username = parts[0]
                        hashed_password = parts[1]  # hashed_password
                        org = parts[5]
                        users[username] = hashed_password
                        
        return users, org

    #get user data
    def get_user_data(username, filename=USER_DATA_FILE):
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(',')
                if parts[0] == username:
                    return {
                        'username': parts[0],
                        'first_name': parts[2],
                        'last_name': parts[3],
                        'email': parts[4],
                        'organization': parts[5]
                    }
        return None  

    # save user profile
    def save_user_profile(username, first_name, last_name, email, organization, filename=USER_DATA_FILE):
        lines = []
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(',')
                if parts[0] == username:
                    parts[2] = first_name
                    parts[3] = last_name
                    parts[4] = email
                    parts[5] = organization
                    line = ','.join(parts) + '\n'
                lines.append(line)

        with open(filename, 'w', encoding='utf-8') as f:
            f.writelines(lines)

    # verify password
    def verify_password(username, current_password, filename=USER_DATA_FILE):
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(',')
                if parts[0] == username:
                    hashed_password = parts[1]
                    return check_password_hash(hashed_password, current_password)
        return False  

    # update(change) password
    def update_password(username, new_password, filename=USER_DATA_FILE):
        hashed_password = generate_password_hash(new_password, method='pbkdf2:sha256')
        lines = []
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(',')
                if parts[0] == username:
                    parts[1] = hashed_password
                    line = ','.join(parts) + '\n'
                lines.append(line)
        with open(filename, 'w', encoding='utf-8') as f:
            f.writelines(lines)