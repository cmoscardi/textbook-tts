
import gc
import logging
import os
import sys
import threading
import time
import uuid
from collections import namedtuple
from io import BytesIO
from chatterbox.tts import ChatterboxTTS
from celery import Celery
from celery.signals import task_postrun
from doctr.io import DocumentFile
from doctr.models import ocr_predictor
import requests
import torchaudio as ta
from supabase import create_client, Client
from pydub import AudioSegment
import worker_utils as wu
from worker_utils import (
    get_file_info,
    create_parsing_record,
    update_parsing_progress,
    finalize_parsing,
    upload_audio_file,
    generate_output_file_path
)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

rabbitmq_host = os.environ.get("RABBITMQ_HOST")
postgres_url = os.environ.get("DATABASE_CELERY_URL")
logger.info(f"Initializing Celery with RabbitMQ host: {rabbitmq_host}")
app = Celery(__name__, broker=f'pyamqp://guest@{rabbitmq_host}//', backend=postgres_url)

# Celery configuration for long-running GPU tasks
app.conf.update(
    broker_heartbeat=0,  # Disable heartbeat timeout for long-running tasks
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=None,  # Unlimited reconnection attempts
    task_acks_late=True,  # Only acknowledge task after it completes
    worker_prefetch_multiplier=1,  # Only fetch one task at a time (important for GPU)
    task_soft_time_limit=600,  # 10 minutes soft limit
    task_time_limit=900,  # 15 minutes hard limit

    # Task routing configuration
    task_routes={
        'ml_worker.parse_pdf_task': {'queue': 'parse_queue'},
    },
)

supabase = wu.initialize_supabase()

# Initialize the OCR predictor
import torch
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

# CUDA health check at worker startup
if torch.cuda.is_available():
    try:
        logger.info("Running CUDA device health check at worker startup...")
        torch.cuda.synchronize()
        # Test GPU responsiveness with simple operation
        test_tensor = torch.zeros(1).cuda()
        del test_tensor
        torch.cuda.empty_cache()
        logger.info("CUDA device health check passed - GPU is responsive")
    except Exception as e:
        logger.error(f"CUDA device health check FAILED: {e}")
        logger.error("GPU may be in an unresponsive state. Worker will exit.")
        # Exit immediately - Docker health check or monitoring script will restart
        os._exit(1)
else:
    logger.warning("CUDA not available at worker startup")

# ============================================================================
# SINGLETON MODEL INITIALIZATION
# ============================================================================

# Global singleton model instances (initialized at worker startup)
pdf_converter = None
tts_model = None

def initialize_parser_models():
    """Initialize PDF parsing models (parser worker only)

    This loads the marker-pdf PdfConverter once at worker startup.
    The model stays in GPU memory and is reused across all parse tasks.
    """
    global pdf_converter

    if pdf_converter is not None:
        logger.info("PDF converter already initialized")
        return

    logger.info("=" * 60)
    logger.info("INITIALIZING PDF CONVERTER SINGLETON")
    logger.info("=" * 60)
    logger.info(f"GPU memory before model load: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")

    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict

    # Configure batch sizes to minimize VRAM usage
    config = {
        "recognition_batch_size": 1,
        "layout_batch_size": 1,
        "detection_batch_size": 1,
        "ocr_error_batch_size": 1
    }

    pdf_converter = PdfConverter(
        artifact_dict=create_model_dict(),
        config=config,
    )

    logger.info(f"GPU memory after model load: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
    logger.info("PDF converter singleton initialized successfully")
    logger.info("This model will be reused for all parse tasks")
    logger.info("=" * 60)

def initialize_converter_models():
    """Initialize TTS models (converter worker only)

    This loads ChatterboxTTS once at worker startup.
    The model stays in GPU memory and is reused across all convert tasks.
    """
    global tts_model

    if tts_model is not None:
        logger.info("TTS model already initialized")
        return

    logger.info("=" * 60)
    logger.info("INITIALIZING CHATTERBOX TTS SINGLETON")
    logger.info("=" * 60)
    logger.info(f"GPU memory before model load: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")

    from chatterbox.tts import ChatterboxTTS

    tts_model = ChatterboxTTS.from_pretrained(device="cuda")

    logger.info(f"GPU memory after model load: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
    logger.info("ChatterboxTTS singleton initialized successfully")
    logger.info("This model will be reused for all convert tasks")
    logger.info("=" * 60)

# Worker startup: Initialize models based on WORKER_TYPE environment variable
worker_type = os.environ.get("WORKER_TYPE")

if worker_type == "parser":
    logger.info("Worker type: PARSER - Loading PDF parsing models...")
    if torch.cuda.is_available():
        initialize_parser_models()
    else:
        logger.warning("CUDA not available - parser models will be loaded on-demand (dev mode)")

elif worker_type == "converter":
    logger.info("Worker type: CONVERTER - Loading TTS models...")
    if torch.cuda.is_available():
        initialize_converter_models()
    else:
        logger.warning("CUDA not available - TTS models will be loaded on-demand (dev mode)")

else:
    logger.info(f"Worker type: {worker_type or 'NONE'} - No models loaded (API mode)")

def clean_markdown_for_tts(text: str) -> str:
    """Clean markdown text to make it suitable for text-to-speech

    Removes markdown formatting while preserving the natural reading flow.
    Keeps numbered lists as they read well in TTS.

    Args:
        text: Raw markdown text

    Returns:
        Cleaned text suitable for TTS
    """
    import re

    if not text:
        return ""

    # Remove code blocks (must be done before inline code)
    text = re.sub(r'```[\s\S]*?```', '', text)

    # Remove inline code backticks
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Convert links [text](url) to just the text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # Remove images ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', '', text)

    # Remove reference-style links [text][ref]
    text = re.sub(r'\[([^\]]+)\]\[[^\]]*\]', r'\1', text)

    # Remove link references [ref]: url
    text = re.sub(r'^\[[^\]]+\]:\s*.*$', '', text, flags=re.MULTILINE)

    # Remove header markers (# ## ###) but keep the text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Remove bold/italic markers
    text = re.sub(r'\*\*\*([^*]+)\*\*\*', r'\1', text)  # Bold+italic
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)      # Bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)          # Italic
    text = re.sub(r'___([^_]+)___', r'\1', text)        # Bold+italic
    text = re.sub(r'__([^_]+)__', r'\1', text)          # Bold
    text = re.sub(r'_([^_]+)_', r'\1', text)            # Italic

    # Remove strikethrough
    text = re.sub(r'~~([^~]+)~~', r'\1', text)

    # Remove bullet list markers (-, *, +) but KEEP numbered lists
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)

    # Remove horizontal rules
    text = re.sub(r'^[\s]*[-*_]{3,}[\s]*$', '', text, flags=re.MULTILINE)

    # Remove HTML tags (if any)
    text = re.sub(r'<[^>]+>', '', text)

    # Remove blockquote markers
    text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)

    # Remove table formatting (basic approach)
    # Remove table separator lines like |---|---|
    text = re.sub(r'^\|?[\s]*:?-+:?[\s]*\|[\s]*:?-+:?[\s]*.*$', '', text, flags=re.MULTILINE)
    # Remove table cell markers but keep content
    text = re.sub(r'\|', ' ', text)

    # Normalize whitespace
    # Replace multiple spaces with single space
    text = re.sub(r' +', ' ', text)
    # Replace multiple newlines with double newline (paragraph breaks)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove trailing/leading whitespace from lines
    text = '\n'.join(line.strip() for line in text.split('\n'))
    # Remove leading/trailing whitespace from entire text
    text = text.strip()

    return text


# Progress monitoring helper functions for tqdm output parsing
def _parse_tqdm_line(line):
    """Parse tqdm progress line and extract percentage and description

    Args:
        line: String like "Recognizing Text:  99%|#########9| 852/857 [01:50<00:00, 27.30it/s]"

    Returns:
        tuple: (description, percent, current, total) or None if not a tqdm line
    """
    import re

    # Match tqdm format: "Description: XX%|bar| current/total [...]"
    # Also handle carriage returns (\r or ^M)
    line = line.strip().replace('\r', '').replace('^M', '')

    # Pattern: capture description, percentage, current/total
    pattern = r'^(.+?):\s+(\d+)%\|.+?\|\s+(\d+)/(\d+)'
    match = re.match(pattern, line)

    if match:
        description = match.group(1).strip()
        percent = int(match.group(2))
        current = int(match.group(3))
        total = int(match.group(4))
        return (description, percent, current, total)

    return None


def _map_stage_to_progress(stage_name, stage_percent):
    """Map marker-pdf stage and its percent to overall progress

    Args:
        stage_name: Name of the tqdm stage (e.g., "Recognizing Text")
        stage_percent: Progress within that stage (0-100)

    Returns:
        int: Overall progress percentage (15-80)
    """
    # Define stage ranges
    stage_ranges = {
        'Recognizing Layout': (15, 20),
        'Running OCR Error Detection': (20, 25),
        'Detecting bboxes': (25, 30),  # First occurrence
        'Recognizing Text': (30, 75),  # Main work - 45% range
    }

    # Get range for this stage
    if stage_name in stage_ranges:
        start, end = stage_ranges[stage_name]
        # Map stage percent (0-100) to overall range
        overall_progress = start + (end - start) * (stage_percent / 100)
        return int(overall_progress)

    # Unknown stage - return midpoint or last known progress
    return None


def _monitor_tqdm_output(stderr_reader, parsing_id, stop_event):
    """Background thread that monitors stderr and updates progress

    Args:
        stderr_reader: io.TextIOWrapper reading from captured stderr
        parsing_id: Database record ID
        stop_event: Threading event to signal completion
    """
    last_progress = 15
    current_stage = None

    while not stop_event.is_set():
        try:
            line = stderr_reader.readline()
            if not line:
                # EOF or no data
                time.sleep(0.1)
                continue

            # Parse tqdm line
            parsed = _parse_tqdm_line(line)
            if parsed:
                description, percent, current, total = parsed

                # Map to overall progress
                overall_progress = _map_stage_to_progress(description, percent)

                if overall_progress and overall_progress > last_progress:
                    logger.info(f"Progress update: {description} {percent}% -> overall {overall_progress}%")
                    update_parsing_progress(parsing_id, overall_progress, supabase=supabase)
                    last_progress = overall_progress
                    current_stage = description

        except Exception as e:
            logger.warning(f"Error parsing tqdm output: {e}")
            continue


@app.task()
def parse_pdf_task(file_id):
    """Parse PDF and extract text, saving to database"""
    logger.info(f"Starting parse_pdf_task for file_id: {file_id}")

    # Get the current task ID
    task_id = parse_pdf_task.request.id
    parsing_id = None
    temp_file = None

    try:
        # Get file information and signed URL
        file_info = get_file_info(file_id, supabase)
        if not file_info:
            logger.error(f"Could not get file information for file_id: {file_id}")
            return {"error": "Invalid file_id or file not found"}

        # Create parsing record in database
        parsing_id = create_parsing_record(file_id, task_id, supabase)
        if not parsing_id:
            logger.warning("Could not create parsing record - continuing without database tracking")

        # Check if CUDA devices are available
        if not torch.cuda.is_available():
            logger.warning("No CUDA device available - returning dev mode message")
            if parsing_id:
                finalize_parsing(parsing_id, file_id, "dev mode text", "completed", supabase=supabase)
            return "no cuda device -- dev mode"

        logger.info("CUDA device available, proceeding with parsing")
        update_parsing_progress(parsing_id, 5, "running", supabase=supabase)

        # Clear GPU memory at task start to ensure maximum available memory
        logger.info(f"GPU memory before clearing: allocated={torch.cuda.memory_allocated() / 1024**3:.2f} GB, reserved={torch.cuda.memory_reserved() / 1024**3:.2f} GB")
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.empty_cache()  # Call twice to help with fragmentation
        torch.cuda.ipc_collect()  # Clean up inter-process shared memory
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.reset_accumulated_memory_stats()
        logger.info(f"GPU memory after clearing: allocated={torch.cuda.memory_allocated() / 1024**3:.2f} GB, reserved={torch.cuda.memory_reserved() / 1024**3:.2f} GB")

        start = time.time()

        # Download the file from the signed URL
        logger.info(f"Downloading PDF from signed URL")
        response = requests.get(file_info.signed_url)
        response.raise_for_status()

        # Save to temporary file
        temp_file = f"/tmp/download_{task_id}.pdf"
        with open(temp_file, "wb") as f:
            f.write(response.content)
        logger.info(f"Downloaded PDF to: {temp_file}")

        update_parsing_progress(parsing_id, 10, supabase=supabase)

        # Use singleton PDF converter
        logger.info("Using singleton PDF converter (no reload)")
        if pdf_converter is None:
            # Dev mode fallback: initialize on-demand if not loaded at startup
            logger.warning("Singleton not initialized, loading on-demand (dev mode)")
            initialize_parser_models()

        update_parsing_progress(parsing_id, 15, supabase=supabase)

        logger.info("Starting PDF conversion with tqdm progress monitoring")

        # Create a pipe to capture stderr
        stderr_pipe_read, stderr_pipe_write = os.pipe()

        # Thread to monitor stderr
        stop_event = threading.Event()
        stderr_reader = os.fdopen(stderr_pipe_read, 'r')
        monitor_thread = threading.Thread(
            target=_monitor_tqdm_output,
            args=(stderr_reader, parsing_id, stop_event),
            daemon=True
        )
        monitor_thread.start()

        # Temporarily redirect stderr to our pipe
        old_stderr = sys.stderr
        try:
            sys.stderr = os.fdopen(stderr_pipe_write, 'w')

            # Run conversion with stderr redirected
            res = pdf_converter(temp_file)
            text, _, images = text_from_rendered(res)

        finally:
            # Restore stderr
            sys.stderr = old_stderr

            # Stop monitoring thread
            stop_event.set()
            monitor_thread.join(timeout=2)

        logger.info(f"PDF conversion complete, extracted {len(text)} characters")
        update_parsing_progress(parsing_id, 80, supabase=supabase)

        # Cleanup intermediate results only (NOT the singleton model)
        logger.info("Cleaning up intermediate conversion results (keeping singleton)")
        del res
        if images:
            del images

        gc.collect()
        torch.cuda.empty_cache()
        logger.info(f"GPU memory allocated after cleanup: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
        update_parsing_progress(parsing_id, 85, supabase=supabase)

        # Store original raw markdown
        raw_markdown = text
        logger.info(f"Stored raw markdown ({len(raw_markdown)} characters)")

        # Clean markdown for TTS
        logger.info("Cleaning markdown for TTS")
        cleaned_text = clean_markdown_for_tts(text)
        logger.info(f"Cleaned text for TTS ({len(cleaned_text)} characters)")
        update_parsing_progress(parsing_id, 90, supabase=supabase)

        # Text preprocessing - split into sentences
        import re
        sentences = re.split(r'(?<=[.!?]) +', cleaned_text)
        logger.info(f"Split text into {len(sentences)} sentences")

        # Save the parsed text (cleaned version)
        parsed_text = cleaned_text
        update_parsing_progress(parsing_id, 95, supabase=supabase)

        # Save to database (both raw markdown and cleaned text)
        logger.info(f"Saving parsed text and raw markdown to database")
        finalize_parsing(parsing_id, file_id, parsed_text, "completed", raw_markdown=raw_markdown, supabase=supabase)
        update_parsing_progress(parsing_id, 100, supabase=supabase)

        # Clean up temporary file
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
            logger.info(f"Cleaned up temporary file: {temp_file}")

        end = time.time()
        processing_time = end - start
        logger.info(f"Parsing completed in {processing_time:.2f} seconds")

        return {
            "status": "completed",
            "parsing_id": parsing_id,
            "text_length": len(parsed_text),
            "sentence_count": len(sentences),
            "processing_time": processing_time
        }

    except Exception as e:
        logger.error(f"Error in parse_pdf_task: {str(e)}")
        if parsing_id:
            try:
                # Update parsing record with error
                update_data = {
                    "status": "failed",
                    "job_completion": 0,
                    "error_message": str(e)
                }
                supabase.table("file_parsings").update(update_data).eq("parsing_id", parsing_id).execute()
            except:
                pass

        # Cleanup on error
        try:
            # Clean up intermediate results only (keep singleton)
            # NO cleanup of pdf_converter - it's a singleton
            if 'res' in locals():
                del res
            if 'images' in locals():
                del images
            if 'text' in locals():
                del text
            if 'sentences' in locals():
                del sentences

            gc.collect()
            torch.cuda.empty_cache()
            logger.info(f"GPU memory allocated after error cleanup: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
        except Exception as cleanup_err:
            logger.warning(f"Error during GPU cleanup: {cleanup_err}")

        # Clean up temporary file
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass

        raise e
