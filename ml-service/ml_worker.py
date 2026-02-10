
import gc
import logging
import os
import re
import time
from celery import Celery
import requests
from pypdf import PdfReader, PdfWriter
from supabase import create_client, Client
import worker_utils as wu
from worker_utils import (
    get_file_info,
    create_parsing_record,
    update_parsing_progress,
    finalize_parsing,
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
from marker.schema import BlockTypes

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

# Global singleton model instance (initialized at worker startup)
pdf_converter = None

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

# Worker startup: Initialize models based on WORKER_TYPE environment variable
worker_type = os.environ.get("WORKER_TYPE")

if worker_type == "parser":
    logger.info("Worker type: PARSER - Loading PDF parsing models...")
    if torch.cuda.is_available():
        initialize_parser_models()
    else:
        logger.warning("CUDA not available - parser models will be loaded on-demand (dev mode)")
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


# Block types that contain readable text for sentence extraction
_TEXT_BLOCK_TYPES = (
    BlockTypes.Text,
    BlockTypes.SectionHeader,
    BlockTypes.ListItem,
    BlockTypes.Caption,
    BlockTypes.Footnote,
    BlockTypes.TextInlineMath,
)


def extract_pages_and_sentences(document):
    """Extract page dimensions and sentences with bounding boxes from a marker Document.

    Traverses the Document's page/block/line hierarchy to produce sentence-level
    data with polygon coordinates from the underlying visual lines.

    Args:
        document: A marker Document object (from PdfConverter.build_document)

    Returns:
        list of dicts, one per page:
        {
            "page_number": int (0-indexed),
            "width": float,
            "height": float,
            "sentences": [
                {"text": str, "bbox": [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], ...]},
                ...
            ]
        }
    """
    sentence_split = re.compile(r'(?<=[.!?])\s+')

    pages_data = []

    for page_idx, page in enumerate(document.pages):
        page_info = {
            "page_number": page_idx,
            "width": page.polygon.width,
            "height": page.polygon.height,
            "sentences": []
        }

        # Get all text-type blocks on this page
        text_blocks = page.contained_blocks(document, _TEXT_BLOCK_TYPES)

        for block in text_blocks:
            # Get lines within this block
            lines = block.contained_blocks(document, (BlockTypes.Line,))
            if not lines:
                continue

            # Collect each line's text and polygon
            line_texts = []
            line_polygons = []
            for line in lines:
                lt = line.raw_text(document).rstrip('\n')
                line_texts.append(lt)
                line_polygons.append(line.polygon.polygon)

            # Build concatenated block text with spaces between lines,
            # tracking which character index maps to which line
            block_text = ""
            char_to_line = []
            for i, lt in enumerate(line_texts):
                if i > 0:
                    block_text += " "
                    char_to_line.append(i)  # space belongs to next line
                for _ in lt:
                    char_to_line.append(i)
                block_text += lt

            if not block_text.strip():
                continue

            # Split block text into sentences
            sentence_spans = []
            last_end = 0
            for match in sentence_split.finditer(block_text):
                sentence_spans.append((last_end, match.start()))
                last_end = match.end()
            if last_end < len(block_text):
                sentence_spans.append((last_end, len(block_text)))

            for start, end in sentence_spans:
                sentence_text = block_text[start:end].strip()
                if not sentence_text:
                    continue

                # Determine which lines this sentence spans
                spanned_line_indices = set()
                for char_idx in range(start, min(end, len(char_to_line))):
                    spanned_line_indices.add(char_to_line[char_idx])

                # Collect the polygons of those lines
                sentence_polygons = [line_polygons[li] for li in sorted(spanned_line_indices)]

                page_info["sentences"].append({
                    "text": sentence_text,
                    "bbox": sentence_polygons
                })

        # Merge short sentences (<150 chars) with the next one
        merged = []
        for sent in page_info["sentences"]:
            if merged and len(merged[-1]["text"]) < 150:
                merged[-1]["text"] += " " + sent["text"]
                merged[-1]["bbox"].extend(sent["bbox"])
            else:
                merged.append({"text": sent["text"], "bbox": list(sent["bbox"])})

        # If the last entry is still short, fold it into the previous one
        if len(merged) >= 2 and len(merged[-1]["text"]) < 150:
            merged[-2]["text"] += " " + merged[-1]["text"]
            merged[-2]["bbox"].extend(merged[-1]["bbox"])
            merged.pop()

        page_info["sentences"] = merged
        pages_data.append(page_info)

    return pages_data


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

        # Count total pages
        reader = PdfReader(temp_file)
        total_pages = len(reader.pages)
        logger.info(f"PDF has {total_pages} pages")
        update_parsing_progress(parsing_id, 15, supabase=supabase)

        # Delete existing page/sentence data for idempotency
        wu.delete_file_pages(file_id, supabase)

        # Resolve renderer once (reused for all pages)
        renderer = pdf_converter.resolve_dependencies(pdf_converter.renderer)

        all_page_texts = []
        global_sequence = 0

        for page_idx in range(total_pages):
            logger.info(f"Processing page {page_idx + 1}/{total_pages}")

            # Extract single page to temp file
            writer = PdfWriter()
            writer.add_page(reader.pages[page_idx])
            page_file = f"/tmp/download_{task_id}_page_{page_idx}.pdf"
            with open(page_file, "wb") as f:
                writer.write(f)

            try:
                # Run marker on single page
                document = pdf_converter.build_document(page_file)
                res = renderer(document)
                page_text, _, page_images = text_from_rendered(res)
                all_page_texts.append(page_text)

                # Extract sentences + bboxes from this page's Document
                page_data_list = extract_pages_and_sentences(document)

                # Clean up GPU memory for this page
                del res, document
                if page_images:
                    del page_images
                gc.collect()
                torch.cuda.empty_cache()

                # Save page + sentences to DB immediately
                if page_data_list:
                    pd = page_data_list[0]
                    page_id = wu.create_file_page(
                        file_id=file_id,
                        page_number=page_idx,
                        width=pd["width"],
                        height=pd["height"],
                        markdown_text=page_text,
                        supabase=supabase
                    )
                    if page_id and pd["sentences"]:
                        rows = [{
                            "page_id": page_id,
                            "file_id": file_id,
                            "text": s["text"],
                            "sequence_number": global_sequence + i,
                            "bbox": s["bbox"]
                        } for i, s in enumerate(pd["sentences"])]
                        wu.create_page_sentences_bulk(rows, supabase)
                        global_sequence += len(rows)

            except Exception as page_err:
                logger.error(f"Failed to process page {page_idx}: {page_err}")
            finally:
                if os.path.exists(page_file):
                    os.remove(page_file)

            # Update progress: 15% -> 85% proportional to pages
            progress = 15 + int(70 * (page_idx + 1) / total_pages)
            update_parsing_progress(parsing_id, progress, supabase=supabase)

        logger.info(f"Processed {total_pages} pages, {global_sequence} total sentences")

        # Combine all page texts into flat markdown
        text = "\n\n".join(all_page_texts)
        raw_markdown = text
        logger.info(f"Combined raw markdown ({len(raw_markdown)} characters)")

        # Clean markdown for TTS
        logger.info("Cleaning markdown for TTS")
        cleaned_text = clean_markdown_for_tts(text)
        logger.info(f"Cleaned text for TTS ({len(cleaned_text)} characters)")
        update_parsing_progress(parsing_id, 90, supabase=supabase)

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
            "sentence_count": global_sequence,
            "page_count": total_pages,
            "processing_time": processing_time
        }

    except Exception as e:
        logger.error(f"Error in parse_pdf_task: {str(e)}")
        if parsing_id:
            try:
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
            gc.collect()
            torch.cuda.empty_cache()
            logger.info(f"GPU memory allocated after error cleanup: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
        except Exception as cleanup_err:
            logger.warning(f"Error during GPU cleanup: {cleanup_err}")

        # Clean up temporary files
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass

        raise e
