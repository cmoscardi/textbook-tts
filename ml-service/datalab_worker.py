import html as html_module
import os
import gc
import logging
import re
import time
from celery import Celery
import requests
from pypdf import PdfReader

import worker_utils as wu
from email_alerts import setup_email_logging, register_celery_failure_handler
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
    split_and_merge_sentences,
    extract_sentences_from_block,
    merge_short_sentences_with_bbox,
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
    start_http_server(9093)
    logger.info("Prometheus metrics server started on port 9093")
except OSError as e:
    logger.warning(f"Could not start Prometheus metrics server on port 9093: {e}")

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
    task_soft_time_limit=600,
    task_time_limit=900,
    result_expires=300,

    task_routes={
        'datalab_worker.parse_pdf_datalab_task': {'queue': 'datalab_parse_queue'},
    },
)
register_celery_failure_handler(app)

DATALAB_API_KEY = os.environ.get("DATALAB_API_KEY", "")
DEV_MODE = not DATALAB_API_KEY

if DEV_MODE:
    logger.info("Datalab worker running in DEV MODE (no API key set, will use stub data)")
else:
    logger.info("Datalab worker running in PRODUCTION MODE")


_DATALAB_TEXT_BLOCK_TYPES = {
    "Text", "SectionHeader", "ListItem", "Caption", "Footnote", "TextInlineMath"
}

_HTML_TAG_RE = re.compile(r'<[^>]+>')


def extract_pages_from_datalab_json(json_data: dict) -> list[dict]:
    """Extract pages and sentences with bboxes from a Datalab JSON conversion result.

    The Datalab JSON (Marker format) has a hierarchy of:
      Document → Page blocks → Text blocks (with polygon) → children

    Each text block's polygon is used as the bbox for all sentences within it,
    using extract_sentences_from_block() with block-level granularity.

    Args:
        json_data: The dict from ConversionResult.json

    Returns:
        list of {"page_number": int, "width": float, "height": float,
                 "sentences": [{"text": str, "bbox": [polygon]}]}
    """
    pages = []
    for page_idx, page_block in enumerate(json_data.get("children", [])):
        if page_block.get("block_type") != "Page":
            continue

        # Extract page dimensions from the Page block's polygon
        page_polygon = page_block.get("polygon", [])
        if len(page_polygon) >= 4:
            # Polygon is [[x0,y0],[x1,y0],[x1,y1],[x0,y1]] — TL,TR,BR,BL
            page_width = page_polygon[2][0]
            page_height = page_polygon[2][1]
        else:
            page_width, page_height = 0, 0

        sentences = []
        for block in page_block.get("children", []):
            if block.get("block_type") not in _DATALAB_TEXT_BLOCK_TYPES:
                continue
            raw_html = block.get("html", "")
            block_text = html_module.unescape(_HTML_TAG_RE.sub("", raw_html)).strip()
            if not block_text:
                continue
            polygon = block.get("polygon")
            if not polygon:
                continue
            sentences.extend(extract_sentences_from_block(block_text, [block_text], [polygon]))
        pages.append({
            "page_number": page_idx,
            "width": page_width,
            "height": page_height,
            "sentences": merge_short_sentences_with_bbox(sentences),
        })
    return pages


def _dev_mode_parse(file_id, parsing_id, task_id):
    """Dev mode: sleep 10s and generate stub data."""
    logger.info(f"[DEV MODE] Simulating Datalab parse for file {file_id}")
    update_parsing_progress(parsing_id, 10, "running", supabase=supabase)

    time.sleep(10)
    update_parsing_progress(parsing_id, 50, supabase=supabase)

    stub_sentences = [
        "Dev mode: Datalab API key not set, so cloud parsing is skipped.",
        "This document contains placeholder sentences generated by the Datalab fallback worker.",
        "In production, the Datalab API parses the PDF when the GPU parser is busy.",
        "The parsed text is stored in the database just like GPU-parsed documents.",
        "Sentences are extracted and stored with sequence numbers for ordered playback.",
        "The text-to-speech pipeline converts each sentence into an audio clip.",
        "This stub simulates a 10-second processing delay to mimic real API latency.",
        "Each sentence is synthesized independently and cached for future playback.",
        "The frontend highlights the current sentence as audio plays back.",
        "Bounding box data links each sentence to its position on the original PDF page.",
        "Users can click on any sentence to jump to that point in the audio.",
        "Playback speed can be adjusted from one times to two times normal speed.",
        "The load testing framework simulates multiple concurrent users.",
        "Parse jobs are routed to the GPU parser or Datalab API based on availability.",
        "RabbitMQ distributes tasks across available worker processes.",
        "Celery manages task execution, retries, and result storage.",
        "The marker PDF library extracts structured text with layout information.",
        "Page-level metadata includes dimensions and raw markdown content.",
        "Audio files are stored in Supabase storage under each user's folder.",
        "Row-level security ensures users can only access their own documents.",
        "The subscription system tracks page usage against tier limits.",
        "Stripe handles payment processing and subscription lifecycle events.",
        "Webhook events from Stripe update the local database in real time.",
        "Email ingestion allows users to send PDFs directly for processing.",
        "Cloudflare workers route inbound emails to the parsing pipeline.",
        "The monitoring stack includes Prometheus, Grafana, and Flower.",
        "Worker health checks verify that GPU and CPU resources are available.",
        "Database migrations are managed through Supabase CLI tooling.",
        "Edge functions handle authentication and route requests to the ML service.",
        "JWT tokens are verified locally to avoid bottlenecks under load.",
        "The nginx reverse proxy handles rate limiting and SSL termination.",
        "Docker containers isolate each service with defined resource limits.",
        "The remote GPU host connects to the main host via a private network.",
        "Celery result backends store task outputs in PostgreSQL with expiry.",
        "Prefetch logic in the frontend keeps audio buffered ahead of playback.",
        "Interruptions are tracked when synthesis cannot keep up with playback.",
        "The conversion pipeline concatenates sentence audio into a full document.",
        "Temporary WAV files are converted to MP3 for efficient storage.",
        "File checksums prevent duplicate uploads of the same document.",
        "User profiles track subscription tier, status, and billing period.",
        "The free tier includes a limited number of pages per billing period.",
        "Pro tier users get higher limits and priority processing.",
        "Usage tracking resets at the start of each billing period.",
        "The cleanup script removes test users and their associated data.",
        "Load test results include latency percentiles and buffering statistics.",
        "First page ready time measures end-to-end responsiveness of parsing.",
        "Synthesis latency varies based on sentence length and server load.",
        "The CAPTCHA system prevents automated abuse of the sign-up flow.",
        "Test mode CAPTCHA tokens bypass verification during load testing.",
        "This is the final sentence in the dev mode stub document.",
    ]
    stub_sentences = stub_sentences * 5
    stub_text = " ".join(stub_sentences)

    delete_file_pages(file_id, supabase)

    page_id = create_file_page(
        file_id=file_id, page_number=0, width=0, height=0,
        markdown_text=stub_text, supabase=supabase
    )

    if page_id:
        merged = split_and_merge_sentences(stub_text)
        rows = [{
            "page_id": page_id,
            "file_id": file_id,
            "text": s,
            "sequence_number": i,
            "bbox": []
        } for i, s in enumerate(merged)]
        create_page_sentences_bulk(rows, supabase)

    update_parsing_progress(parsing_id, 90, supabase=supabase)
    finalize_parsing(parsing_id, file_id, stub_text, "completed",
                     raw_markdown=stub_text, supabase=supabase)
    logger.info(f"[DEV MODE] Stub parse complete for file {file_id}")


@app.task()
def parse_pdf_datalab_task(file_id):
    start = time.time()
    task_id = parse_pdf_datalab_task.request.id
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

        # Create parsing record (handle existing record for idempotency)
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

        # Dev mode: stub data
        if DEV_MODE:
            _dev_mode_parse(file_id, parsing_id, task_id)
            return {"status": "completed", "mode": "dev_stub"}

        update_parsing_progress(parsing_id, 5, "running", supabase=supabase)

        # Download PDF
        logger.info(f"Downloading PDF from signed URL for file {file_id}")
        response = requests.get(file_info.signed_url, timeout=120)
        response.raise_for_status()

        temp_file = f"/tmp/datalab_{task_id}.pdf"
        with open(temp_file, "wb") as f:
            f.write(response.content)

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

        # Call Datalab API
        logger.info(f"Submitting PDF to Datalab API ({total_pages} pages)")
        from datalab_sdk import DatalabClient
        from datalab_sdk.models import ConvertOptions
        client = DatalabClient(api_key=DATALAB_API_KEY)
        result = client.convert(temp_file, options=ConvertOptions(paginate=True, output_format="markdown,json"))
        logger.info("Datalab API returned results")

        update_parsing_progress(parsing_id, 70, supabase=supabase)

        raw_markdown = result.markdown

        # Store pages and sentences — use JSON output for bboxes when available
        delete_file_pages(file_id, supabase)
        global_sequence = 0

        if result.json:
            pages_data = extract_pages_from_datalab_json(result.json)
            logger.info(f"Extracted {len(pages_data)} pages from Datalab JSON")
            for pd in pages_data:
                page_text = " ".join(s["text"] for s in pd["sentences"])
                page_id = create_file_page(
                    file_id=file_id, page_number=pd["page_number"],
                    width=pd["width"], height=pd["height"],
                    markdown_text=page_text, supabase=supabase
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
                    global_sequence += len(pd["sentences"])
        else:
            # Fallback: markdown-only path (no bbox)
            logger.warning("Datalab JSON output unavailable — falling back to markdown-only (no bboxes)")
            page_texts = re.split(r'\n{2,}---\n{2,}', raw_markdown)
            if not page_texts:
                page_texts = [raw_markdown]
            logger.info(f"Split into {len(page_texts)} pages")
            for page_num, page_text in enumerate(page_texts):
                page_text = page_text.strip()
                if not page_text:
                    continue
                page_id = create_file_page(
                    file_id=file_id, page_number=page_num, width=0, height=0,
                    markdown_text=page_text, supabase=supabase
                )
                if page_id:
                    sentences = split_and_merge_sentences(page_text)
                    if sentences:
                        rows = [{
                            "page_id": page_id,
                            "file_id": file_id,
                            "text": s,
                            "sequence_number": global_sequence + i,
                            "bbox": []
                        } for i, s in enumerate(sentences)]
                        create_page_sentences_bulk(rows, supabase)
                        global_sequence += len(sentences)

        update_parsing_progress(parsing_id, 85, supabase=supabase)

        # Clean markdown for TTS and finalize
        parsed_text = clean_markdown_for_tts(raw_markdown)
        total_time = time.time() - start

        finalize_parsing(parsing_id, file_id, parsed_text, "completed",
                         raw_markdown=raw_markdown, total_time=total_time,
                         supabase=supabase)

        logger.info(f"Datalab parse completed in {total_time:.2f}s "
                     f"({global_sequence} sentences)")

        return {
            "status": "completed",
            "parsing_id": parsing_id,
            "sentences": global_sequence,
            "processing_time": total_time
        }

    except Exception as e:
        _status = 'failed'
        logger.error(f"Error in parse_pdf_datalab_task: {str(e)}")

        if parsing_id:
            try:
                supabase.table("file_parsings").update({
                    "status": "failed",
                    "job_completion": 0,
                    "error_message": str(e)
                }).eq("parsing_id", parsing_id).execute()
            except:
                pass

        raise e
    finally:
        celery_tasks_total.labels(task_name='parse_pdf_datalab_task', status=_status).inc()
        celery_task_duration_seconds.labels(task_name='parse_pdf_datalab_task').observe(time.time() - _metric_start)
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
