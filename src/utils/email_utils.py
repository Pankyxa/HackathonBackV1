import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from src.settings import settings

def send_test_email():
    msg = MIMEMultipart()
    msg['From'] = settings.smtp_sender
    msg['To'] = settings.smtp_recipient
    msg['Subject'] = "Тест"
    
    msg.attach(MIMEText("Тест", 'plain'))
    
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.send_message(msg)
            return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False