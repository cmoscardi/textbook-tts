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
    result_expires=300,  # 5 minutes
)

# Task name constants
PARSE_PDF_TASK = 'ml_worker.parse_pdf_task'
PARSE_PDF_DATALAB_TASK = 'datalab_worker.parse_pdf_datalab_task'
FAST_PARSE_TASK = 'fast_parser_worker.fast_parse_pdf_task'
INGEST_EMAIL_TASK = 'ml_worker.ingest_email_task'

# TTS engine selection: task names are derived from the worker module name
TTS_ENGINE = os.environ.get('TTS_ENGINE', 'kitten')
_tts_module = 'kitten_worker' if TTS_ENGINE == 'kitten' else 'supertonic_worker'
CONVERT_TO_AUDIO_TASK = f'{_tts_module}.convert_to_audio_task'
SYNTHESIZE_SENTENCE_TASK = f'{_tts_module}.synthesize_sentence_task'

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

def send_datalab_parse_task(file_id: str):
    """Send PDF parsing task to Datalab API worker (fallback when GPU parser is busy)"""
    logger.info(f"Sending Datalab parse task for file_id: {file_id}")
    return client_app.send_task(
        PARSE_PDF_DATALAB_TASK,
        args=[file_id],
        queue='datalab_parse_queue'
    )

def send_fast_parse_task(file_id: str):
    """Send PDF to fast (PyMuPDF) parser for simple, native-text PDFs"""
    logger.info(f"Sending fast parse task for file_id: {file_id}")
    return client_app.send_task(
        FAST_PARSE_TASK,
        args=[file_id],
        queue='fast_parse_queue'
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

def send_synthesize_task(text: str):
    """Send sentence synthesis task to converter worker

    Args:
        text: The sentence text to synthesize

    Returns:
        AsyncResult: Celery task result object with .id and other methods
    """
    logger.info(f"Sending synthesize task ({len(text)} chars)")
    return client_app.send_task(
        SYNTHESIZE_SENTENCE_TASK,
        args=[text],
        queue='synthesize_queue'
    )

def send_ingest_email_task(email_data: dict):
    """Send email ingestion task to parser worker

    Args:
        email_data: Dict with sender, subject, attachment data, text/html body

    Returns:
        AsyncResult: Celery task result object with .id and other methods
    """
    logger.info(f"Sending ingest-email task for sender: {email_data.get('sender')}")
    return client_app.send_task(
        INGEST_EMAIL_TASK,
        args=[email_data],
        queue='parse_queue'
    )
