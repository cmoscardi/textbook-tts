"""Email alerts for autoscaler events.

Standalone SMTP module — same pattern as ml-service/email_alerts.py.
Reads SMTP config from environment variables.
"""

import logging
import os
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

_SMTP_HOST = os.environ.get("smtp_host", "")
_SMTP_PORT = int(os.environ.get("smtp_port", "587") or "587")
_SMTP_USER = os.environ.get("smtp_user", "")
_SMTP_PASS = os.environ.get("smtp_pass", "")
_SMTP_FROM_ADDR = os.environ.get("smtp_admin_email", "")
_SMTP_FROM_NAME = os.environ.get("smtp_sender_name", "Textbook TTS Autoscaler")
_LOG_EMAIL_TO = os.environ.get("LOG_EMAIL_ADDRESS", "")


def _is_configured():
    return bool(_SMTP_HOST and _SMTP_USER and _SMTP_PASS and _SMTP_FROM_ADDR and _LOG_EMAIL_TO)


def _send_email_sync(subject, body):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{_SMTP_FROM_NAME} <{_SMTP_FROM_ADDR}>"
        msg["To"] = _LOG_EMAIL_TO
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(_SMTP_USER, _SMTP_PASS)
            smtp.sendmail(_SMTP_FROM_ADDR, [_LOG_EMAIL_TO], msg.as_string())
    except Exception as e:
        logger.warning(f"Failed to send alert email: {e}")


def send_alert(subject, body):
    """Fire-and-forget email alert. Returns immediately."""
    if not _is_configured():
        logger.debug(f"Email not configured, skipping alert: {subject}")
        return
    threading.Thread(target=_send_email_sync, args=(subject, body), daemon=True).start()


def alert_scale_up(droplet_name, queue_name, queue_depth):
    subject = f"[autoscaler] Scale UP: {droplet_name}"
    body = (
        f"Created droplet: {droplet_name}\n"
        f"Queue: {queue_name}\n"
        f"Queue depth at decision time: {queue_depth}\n"
    )
    send_alert(subject, body)


def alert_scale_down(droplet_name, queue_name, idle_seconds):
    subject = f"[autoscaler] Scale DOWN: {droplet_name}"
    body = (
        f"Destroyed droplet: {droplet_name}\n"
        f"Queue: {queue_name}\n"
        f"Idle for: {idle_seconds:.0f}s\n"
    )
    send_alert(subject, body)


def alert_capacity_warning(queue_name, queue_depth, max_droplets, active_droplets):
    subject = f"[autoscaler] CAPACITY WARNING: {queue_name}"
    body = (
        f"Queue {queue_name} depth: {queue_depth}\n"
        f"Active droplets: {active_droplets}/{max_droplets} (at max)\n"
        f"Local workers may be overloaded. Consider increasing max_droplets.\n"
    )
    send_alert(subject, body)


def alert_cost_warning(monthly_cost, cost_cap):
    subject = f"[autoscaler] COST WARNING: ${monthly_cost:.2f}/{cost_cap:.2f}"
    body = (
        f"Monthly droplet cost: ${monthly_cost:.2f}\n"
        f"Monthly cap: ${cost_cap:.2f}\n"
        f"Autoscaler will refuse to create new droplets until next month.\n"
    )
    send_alert(subject, body)


def alert_error(error_msg):
    subject = "[autoscaler] ERROR"
    send_alert(subject, error_msg)
