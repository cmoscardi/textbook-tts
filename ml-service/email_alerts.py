import logging
import os
import smtplib
import threading
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

_SMTP_HOST      = os.environ.get("smtp_host", "")
_SMTP_PORT      = int(os.environ.get("smtp_port", "587") or "587")
_SMTP_USER      = os.environ.get("smtp_user", "")
_SMTP_PASS      = os.environ.get("smtp_pass", "")
_SMTP_FROM_ADDR = os.environ.get("smtp_admin_email", "")
_SMTP_FROM_NAME = os.environ.get("smtp_sender_name", "Textbook TTS")
_LOG_EMAIL_TO   = os.environ.get("LOG_EMAIL_ADDRESS", "")


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
    except Exception:
        pass  # Never crash the worker over email


def send_alert(subject, body):
    """Fire-and-forget email alert. Returns immediately; SMTP runs in a daemon thread."""
    if not _is_configured():
        return
    threading.Thread(target=_send_email_sync, args=(subject, body), daemon=True).start()


class EmailAlertHandler(logging.Handler):
    """Logging handler that emails every ERROR (and above) log record."""

    def emit(self, record):
        try:
            short_msg = self.format(record).splitlines()[0][:120]
            subject = f"[ml-service] {record.levelname} in {record.name}: {short_msg}"
            body = self.format(record)
            if record.exc_info:
                body += "\n\nTraceback:\n" + "".join(traceback.format_exception(*record.exc_info))
            send_alert(subject, body)
        except Exception:
            pass


def setup_email_logging():
    """Attach EmailAlertHandler to the root logger. Call once per process."""
    if not _is_configured():
        logging.getLogger().warning(
            "email_alerts: SMTP not fully configured "
            "(smtp_host/smtp_user/smtp_pass/smtp_admin_email/LOG_EMAIL_ADDRESS). "
            "Error email alerts are disabled."
        )
        return
    handler = EmailAlertHandler()
    handler.setLevel(logging.ERROR)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(handler)
    logging.getLogger().info("email_alerts: EmailAlertHandler attached to root logger")


def register_celery_failure_handler(celery_app):
    """Connect to the Celery task_failure signal for explicit task failure alerts."""
    from celery.signals import task_failure

    @task_failure.connect(sender=celery_app)
    def on_task_failure(sender=None, task_id=None, exception=None,
                        args=None, kwargs=None, einfo=None, **kw):
        task_name = sender.name if sender else "unknown_task"
        subject = f"[ml-service] Celery task FAILED: {task_name}"
        body = (
            f"Task ID  : {task_id}\n"
            f"Task name: {task_name}\n"
            f"Exception: {type(exception).__name__}: {exception}\n\n"
            f"Traceback:\n{einfo}"
        )
        send_alert(subject, body)
