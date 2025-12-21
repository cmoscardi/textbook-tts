from celery import Celery
import os
import logging

logger = logging.getLogger(__name__)

# Minimal Celery app - ONLY for sending tasks
rabbitmq_host = os.environ.get("RABBITMQ_HOST")
postgres_url = os.environ.get("DATABASE_CELERY_URL")

client_app = Celery(
    'task_client',
    broker=f'pyamqp://guest@{rabbitmq_host}//',
    backend=postgres_url
)

client_app.conf.update(
    broker_connection_retry_on_startup=True,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
)

# Task name constants
PARSE_PDF_TASK = 'ml_worker.parse_pdf_task'
CONVERT_TO_AUDIO_TASK = 'supertonic_worker.convert_to_audio_task'

def send_parse_task(file_id: str):
    """Send PDF parsing task to parser worker

    Args:
        file_id: UUID string of the file to parse

    Returns:
        AsyncResult: Celery task result object with .id and other methods
    """
    logger.info(f"Sending parse task for file_id: {file_id}")
    return client_app.send_task(
        PARSE_PDF_TASK,
        args=[file_id],
        queue='parse_queue'
    )

def send_convert_task(file_id: str):
    """Send audio conversion task to converter worker

    Args:
        file_id: UUID string of the file to convert

    Returns:
        AsyncResult: Celery task result object with .id and other methods
    """
    logger.info(f"Sending convert task for file_id: {file_id}")
    return client_app.send_task(
        CONVERT_TO_AUDIO_TASK,
        args=[file_id],
        queue='convert_queue'
    )
