"""Minimal Celery app for beat scheduler only.

Connects to the broker and result backend so that celery.backend_cleanup
is triggered daily. No task functions are imported.
"""

import os
from celery import Celery

rabbitmq_host = os.environ.get("RABBITMQ_HOST")
postgres_url = os.environ.get("DATABASE_CELERY_URL")

app = Celery(
    "beat_app",
    broker=f"pyamqp://guest@{rabbitmq_host}//",
    backend=postgres_url,
)

app.conf.update(
    broker_connection_retry_on_startup=True,
    result_expires=300,
)
