import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Optional


def build_email( sender: str, recipients: List[str], subject: str, body_text: Optional[str] = None, 
                body_html: Optional[str] = None, attachments: Optional[List[str]] = None) -> MIMEMultipart:
    """ Build an email message (text + optional HTML + attachments). """
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    # Attach text body
    if body_text:
        msg.attach(MIMEText(body_text, "plain"))

    # Attach HTML body
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    # Attach files
    if attachments:
        for file_path in attachments:
            with open(file_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())

            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{file_path.split("/")[-1]}"',
            )
            msg.attach(part)

    return msg


def send_email(smtp_server: str, port: int, sender: str, password: str, recipients: List[str], message):
    """ Send a pre-built email message. """

    with smtplib.SMTP(smtp_server, port) as server:
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipients, message.as_string())
