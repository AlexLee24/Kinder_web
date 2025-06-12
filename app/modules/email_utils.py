import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from .config import config

def send_invitation_email(email, invitation_link):
    """Send invitation email to user"""
    try:
        if not all([config.SENDER_EMAIL, config.SENDER_PASSWORD]):
            print("Email configuration missing")
            return False
        
        msg = MIMEMultipart()
        msg['From'] = config.SENDER_EMAIL
        msg['To'] = email
        msg['Subject'] = 'Invitation to join Kinder Platform'
        
        body = f"""
        You have been invited to join the Kinder platform.
        
        Click the link below to accept the invitation and create your account:
        {invitation_link}
        
        Best regards,
        Kinder Team
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
        server.starttls()
        server.login(config.SENDER_EMAIL, config.SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Email sending error: {e}")
        return False