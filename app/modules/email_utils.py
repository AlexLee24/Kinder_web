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
        
        msg = MIMEMultipart('alternative')
        msg['From'] = f"Kinder Research Platform <{config.SENDER_EMAIL}>"
        msg['To'] = email
        msg['Subject'] = 'Research Collaboration Invitation - Kinder Platform'
        
        # Plain text version
        text_body = f"""Dear,

We would like to invite you to join the Kinder platform.

Your account has been pre-approved by our team. To complete your registration and access the platform, please use the following secure link:

{invitation_link}

This invitation is valid for 7 days. If you have any questions, please contact our support team.

Best regards,
The Kinder Research Team

---
This is an automated message from the Kinder Platform.
If you received this email in error, please disregard it.
"""

        # Attach both versions
        msg.attach(MIMEText(text_body, 'plain'))
        
        server = smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT)
        server.starttls()
        server.login(config.SENDER_EMAIL, config.SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Email sending error: {e}")