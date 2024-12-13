from werkzeug.security import generate_password_hash

def add_admin_user(username, password, first_name="Admin", last_name="User", email="admin@example.com", organization="GREAT Lab", status="1", filename='users.txt'):
    # 將密碼加密
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    # 生成符合格式的用戶數據行
    user_data = f"{username},{hashed_password},{first_name},{last_name},{email},{organization},{status}\n"
    
    # 將用戶數據寫入文件
    with open(filename, 'a') as f:
        f.write(user_data)
    
    print(f"Admin user '{username}' has been added.")

def add_user(username, password, first_name, last_name, email, organization, status="1", filename='users.txt'):
    # 將密碼加密
    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    # 生成符合格式的用戶數據行
    user_data = f"{username},{hashed_password},{first_name},{last_name},{email},{organization},{status}\n"
    
    # 將用戶數據寫入文件
    with open(filename, 'a') as f:
        f.write(user_data)
    
    print(f"Admin user '{username}' has been added.")


username = input("Enter username for admin: ")
password = input("Enter password for admin: ")
add_admin_user(username, password)

'''
username = input("Enter username: ")
password = input("Enter password: ")
first_name = input("Enter First name: ")
last_name = input("Enter Last name: ")
email = input("Enter email: ")
organization = input("Enter organization: ")
add_user(username, password, first_name, last_name, email, organization)
'''