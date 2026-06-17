from __future__ import annotations

import smtplib
import socket
from email.message import EmailMessage
from pathlib import Path


class EmailNotConfiguredError(RuntimeError):
    pass


def send_result_email(
    smtp_login: str,
    smtp_app_password: str,
    recipient: str,
    attachments: list[Path],
) -> None:
    if not smtp_login or not smtp_app_password:
        raise EmailNotConfiguredError("Yandex SMTP login or app password is empty.")

    message = EmailMessage()
    message["From"] = smtp_login
    message["To"] = recipient
    message["Subject"] = "Готовая свадебная анкета"
    message.set_content(
        "Здравствуйте!\n\nВо вложении готовая свадебная анкета и промпт для подготовки церемонии.\n"
    )

    for path in attachments:
        data = path.read_bytes()
        if path.suffix.lower() == ".docx":
            maintype = "application"
            subtype = "vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            maintype = "text"
            subtype = "plain"
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=path.name)

    try:
        with smtplib.SMTP_SSL("smtp.yandex.ru", 465, timeout=30) as smtp:
            smtp.login(smtp_login, smtp_app_password)
            smtp.send_message(message)
    except (ConnectionRefusedError, TimeoutError, socket.timeout, OSError):
        with smtplib.SMTP("smtp.yandex.ru", 587, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(smtp_login, smtp_app_password)
            smtp.send_message(message)
