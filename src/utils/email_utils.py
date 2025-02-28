import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Union
from src.settings import settings

class EmailSender:
    def __init__(self):
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_sender = settings.smtp_sender

    def _create_message(
        self,
        to_email: Union[str, List[str]],
        subject: str,
        body: str,
        is_html: bool = False
    ) -> MIMEMultipart:
        """
        Создает объект сообщения с заданными параметрами

        Args:
            to_email: Email получателя или список получателей
            subject: Тема письма
            body: Тело письма
            is_html: Флаг, указывающий является ли тело письма HTML

        Returns:
            MIMEMultipart: Подготовленное сообщение
        """
        msg = MIMEMultipart()
        msg['From'] = self.smtp_sender

        if isinstance(to_email, list):
            msg['To'] = ', '.join(to_email)
        else:
            msg['To'] = to_email
        msg['Subject'] = subject

        content_type = 'html' if is_html else 'plain'
        msg.attach(MIMEText(body, content_type))

        return msg

    def send_email(
        self,
        to_email: Union[str, List[str]],
        subject: str,
        body: str,
        is_html: bool = False
    ) -> bool:
        """
        Отправляет email сообщение

        Args:
            to_email: Email получателя или список получателей
            subject: Тема письма
            body: Тело письма
            is_html: Флаг, указывающий является ли тело письма HTML
        Returns:
            bool: True если отправка успешна, False в случае ошибки
        """
        try:
            msg = self._create_message(to_email, subject, body, is_html)

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.send_message(msg)
            return True

        except Exception as e:
            print(f"Error sending email: {e}")
            return False

email_sender = EmailSender()