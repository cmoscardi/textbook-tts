"""Celery worker for fast PDF parsing using PyMuPDF.

Consumes fast_parse_queue. Handles simple, native-text PDFs without GPU.
Falls back to GPU parse_queue if extraction validation fails.
"""

import os
import logging
import time
from celery import Celery
import requests
from pypdf import PdfReader

import worker_utils as wu
from email_alerts import setup_email_logging, register_celery_failure_handler
from fast_parser import (
    extract_pages_and_sentences_fitz,
    generate_markdown_fitz,
    validate_fast_parse,
)
from prometheus_client import Counter, Histogram, start_http_server
from worker_utils import (
    get_file_info,
    create_parsing_record,
    update_parsing_progress,
    finalize_parsing,
    delete_file_pages,
    create_file_page,
    create_page_sentences_bulk,
    clean_markdown_for_tts,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
setup_email_logging()

celery_tasks_total = Counter(
    'celery_tasks_total', 'Total Celery tasks processed',
    ['task_name', 'status']
)
celery_task_duration_seconds = Histogram(
    'celery_task_duration_seconds', 'Celery task execution duration in seconds',
    ['task_name']
)

try:
    start_http_server(9094)
    logger.info("Prometheus metrics server started on port 9094")
except OSError as e:
    logger.warning(f"Could not start Prometheus metrics server on port 9094: {e}")

rabbitmq_host = os.environ.get("RABBITMQ_HOST")
postgres_url = os.environ.get("DATABASE_CELERY_URL")
logger.info(f"Initializing Celery with RabbitMQ host: {rabbitmq_host}")

supabase = wu.initialize_supabase()

rabbitmq_user = os.environ.get("RABBITMQ_USER", "guest")
rabbitmq_pass = os.environ.get("RABBITMQ_PASS", "guest")
app = Celery(__name__, broker=f'pyamqp://{rabbitmq_user}:{rabbitmq_pass}@{rabbitmq_host}//', backend=postgres_url)

app.conf.update(
    broker_heartbeat=0,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=None,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=120,   # 2 min soft (fast parsing shouldn't take long)
    task_time_limit=180,        # 3 min hard
    result_expires=300,

    task_routes={
        'fast_parser_worker.fast_parse_pdf_task': {'queue': 'fast_parse_queue'},
    },
)
register_celery_failure_handler(app)


def _reroute_to_gpu(file_id, parsing_id):
    """Re-route a PDF to the GPU parse queue after fast parse fails validation."""
    from task_client import send_parse_task
    logger.info(f"Re-routing file {file_id} to GPU parse queue")

    # Reset parsing record so GPU worker can start fresh
    if parsing_id:
        try:
            supabase.table("file_parsings").update({
                "status": "pending",
                "job_completion": 0,
                "error_message": "Re-routed from fast parser to GPU"
            }).eq("parsing_id", parsing_id).execute()
        except Exception as e:
            logger.warning(f"Could not reset parsing record: {e}")

    send_parse_task(file_id)


@app.task()
def fast_parse_pdf_task(file_id):
    """Parse a simple PDF using PyMuPDF (no GPU required).

    If extraction validation fails, re-routes to GPU parse_queue.
    """
    start = time.time()
    task_id = fast_parse_pdf_task.request.id
    parsing_id = None
    temp_file = None
    _metric_start = time.time()
    _status = 'success'

    try:
        # Get file information
        file_info = get_file_info(file_id, supabase)
        if not file_info:
            logger.error(f"Could not get file information for file_id: {file_id}")
            return {"error": "Invalid file_id or file not found"}

        # Create parsing record
        parsing_id = create_parsing_record(file_id, task_id, supabase)
        already_charged = False
        if not parsing_id:
            existing = supabase.table("file_parsings").select("parsing_id,status").eq("file_id", file_id).execute()
            if existing.data:
                existing_record = existing.data[0]
                if existing_record['status'] == 'completed':
                    logger.info(f"File {file_id} already parsed successfully, skipping")
                    return {"status": "already_completed"}
                parsing_id = existing_record['parsing_id']
                already_charged = True
                logger.warning(f"Redelivered task for file {file_id}, skipping usage increment")
            else:
                logger.warning("Could not create parsing record - continuing without tracking")

        update_parsing_progress(parsing_id, 5, "running", supabase=supabase)

        # Download PDF
        logger.info(f"Downloading PDF from signed URL for file {file_id}")
        response = requests.get(file_info.signed_url, timeout=120)
        response.raise_for_status()

        temp_file = f"/tmp/fast_parse_{task_id}.pdf"
        with open(temp_file, "wb") as f:
            f.write(response.content)

        update_parsing_progress(parsing_id, 10, supabase=supabase)

        # Count pages and check quota
        reader = PdfReader(temp_file)
        total_pages = len(reader.pages)
        logger.info(f"PDF has {total_pages} pages")

        if not already_charged:
            logger.info(f"Checking page quota for user {file_info.user_id} ({total_pages} pages)")
            try:
                supabase.rpc('increment_page_usage', {
                    'p_user_id': file_info.user_id,
                    'p_page_count': total_pages
                }).execute()
                logger.info(f"Page quota reserved for {total_pages} pages")
            except Exception as quota_err:
                logger.warning(f"Page quota exceeded for user {file_info.user_id}: {quota_err}")
                if parsing_id:
                    supabase.table("file_parsings").update({
                        "status": "failed",
                        "job_completion": 0,
                        "error_message": "Page limit reached"
                    }).eq("parsing_id", parsing_id).execute()
                return {"error": "Page limit reached"}

        update_parsing_progress(parsing_id, 15, supabase=supabase)

        # Extract sentences with bboxes using PyMuPDF
        logger.info(f"Fast parsing {total_pages} pages with PyMuPDF")
        pages_data = extract_pages_and_sentences_fitz(temp_file)

        time_to_first_page = time.time() - start

        # Validate extraction quality
        if not validate_fast_parse(pages_data, total_pages):
            logger.warning(f"Fast parse validation failed for file {file_id}, re-routing to GPU")
            delete_file_pages(file_id, supabase)
            _reroute_to_gpu(file_id, parsing_id)
            return {"status": "rerouted_to_gpu", "file_id": file_id}

        update_parsing_progress(parsing_id, 50, supabase=supabase)

        # Generate markdown
        page_markdowns = generate_markdown_fitz(temp_file)

        update_parsing_progress(parsing_id, 60, supabase=supabase)

        # Store pages and sentences
        delete_file_pages(file_id, supabase)
        global_sequence = 0

        for page_idx, pd in enumerate(pages_data):
            markdown_text = page_markdowns[page_idx] if page_idx < len(page_markdowns) else ""

            page_id = create_file_page(
                file_id=file_id,
                page_number=pd["page_number"],
                width=pd["width"],
                height=pd["height"],
                markdown_text=markdown_text,
                supabase=supabase,
            )

            if page_id and pd["sentences"]:
                rows = [{
                    "page_id": page_id,
                    "file_id": file_id,
                    "text": s["text"],
                    "sequence_number": global_sequence + i,
                    "bbox": s["bbox"],
                } for i, s in enumerate(pd["sentences"])]
                create_page_sentences_bulk(rows, supabase)
                global_sequence += len(rows)

            # Progress: 60% -> 85% proportional to pages
            progress = 60 + int(25 * (page_idx + 1) / len(pages_data))
            update_parsing_progress(parsing_id, progress, supabase=supabase)

        # Clean markdown for TTS and finalize
        raw_markdown = "\n\n".join(page_markdowns)
        parsed_text = clean_markdown_for_tts(raw_markdown)
        total_time = time.time() - start

        update_parsing_progress(parsing_id, 90, supabase=supabase)

        finalize_parsing(
            parsing_id, file_id, parsed_text, "completed",
            raw_markdown=raw_markdown, total_time=total_time,
            time_to_first_page=time_to_first_page, supabase=supabase,
        )

        logger.info(
            f"Fast parse completed in {total_time:.2f}s "
            f"({total_pages} pages, {global_sequence} sentences)"
        )

        return {
            "status": "completed",
            "parsing_id": parsing_id,
            "pages": total_pages,
            "sentences": global_sequence,
            "processing_time": total_time,
            "parser": "fast_pymupdf",
        }

    except Exception as e:
        _status = 'failed'
        logger.error(f"Error in fast_parse_pdf_task: {e}")

        if parsing_id:
            try:
                supabase.table("file_parsings").update({
                    "status": "failed",
                    "job_completion": 0,
                    "error_message": str(e)
                }).eq("parsing_id", parsing_id).execute()
            except Exception:
                pass

        raise e
    finally:
        celery_tasks_total.labels(task_name='fast_parse_pdf_task', status=_status).inc()
        celery_task_duration_seconds.labels(task_name='fast_parse_pdf_task').observe(time.time() - _metric_start)
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
