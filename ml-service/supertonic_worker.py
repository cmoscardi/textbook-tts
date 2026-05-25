import os
import gc
import logging
import base64
from celery import Celery
import time

import worker_utils as wu
from email_alerts import setup_email_logging, register_celery_failure_handler
from prometheus_client import Counter, Histogram, start_http_server
from worker_utils import (
    get_file_info,
    get_parsed_text,
    create_conversion_record,
    update_conversion_progress,
    finalize_conversion,
    upload_audio_file,
    generate_output_file_path
)
from supertonic import TTS
import soundfile as sf

from pydub import AudioSegment

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
    start_http_server(9092)
    logger.info("Prometheus metrics server started on port 9092")
except OSError as e:
    logger.warning(f"Could not start Prometheus metrics server on port 9092: {e}")

rabbitmq_host = os.environ.get("RABBITMQ_HOST")
postgres_url = os.environ.get("DATABASE_CELERY_URL")
logger.info(f"Initializing Celery with RabbitMQ host: {rabbitmq_host}")

supabase = wu.initialize_supabase()

rabbitmq_user = os.environ.get("RABBITMQ_USER", "guest")
rabbitmq_pass = os.environ.get("RABBITMQ_PASS", "guest")
app = Celery(__name__, broker=f'pyamqp://{rabbitmq_user}:{rabbitmq_pass}@{rabbitmq_host}//', backend=postgres_url)

# Celery configuration for long-running TTS tasks
app.conf.update(
    broker_heartbeat=0,  # Disable heartbeat timeout for long-running tasks
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=None,  # Unlimited reconnection attempts
    task_acks_late=True,  # Only acknowledge task after it completes
    worker_prefetch_multiplier=1,  # Only fetch one task at a time (important for TTS)
    task_soft_time_limit=600,  # 10 minutes soft limit
    task_time_limit=900,  # 15 minutes hard limit
    result_expires=300,  # 5 minutes

    # Task routing configuration
    task_routes={
        'supertonic_converter.convert_to_audio_task': {'queue': 'convert_queue'},
        'supertonic_worker.synthesize_sentence_task': {'queue': 'synthesize_queue'},
    },
)
register_celery_failure_handler(app)

logger.info("Loading tts...")
text_to_speech = TTS(model_dir="/supertonic/assets")

@app.task()
def convert_to_audio_task(file_id):
    start = time.time()
    task_id = convert_to_audio_task.request.id
    conversion_id = None
    temp_wav_file = None
    temp_mp3_file = None
    _metric_start = time.time()
    _status = 'success'
    try:
        # Get file information
        file_info = get_file_info(file_id, supabase)
        if not file_info:
            logger.error(f"Could not get file information for file_id: {file_id}")
            return {"error": "Invalid file_id or file not found"}

        parsed_text = get_parsed_text(file_id, supabase).replace("\n", ". ")
        parsed_text = parsed_text + ("." if not parsed_text.endswith(".") else "")
        #logger.info(f"parsed text: {parsed_text}")
        if not parsed_text:
            logger.error(f"No parsed text found for file_id: {file_id}. Run /parse first.")
            return {"error": "No parsed text found. Please parse the PDF first."}

        logger.info(f"Retrieved parsed text ({len(parsed_text)} characters)")

        # Create conversion record in database
        conversion_id = create_conversion_record(file_id, task_id, supabase=supabase)
        if not conversion_id:
            logger.warning("Could not create conversion record - continuing without database tracking")

        update_conversion_progress(conversion_id, 10, "running", supabase=supabase)
        logger.info("Loading supertonic style")

        style = text_to_speech.get_voice_style("M3")
        logger.info("Running TTS...")
        wav, duration = text_to_speech.synthesize(parsed_text, style, total_steps=10, speed=1.1, lang="en")
        w = wav[0, : int(text_to_speech.sample_rate * duration[0].item())]
        temp_wav_file = f"/tmp/audio_{task_id}.wav"
        logger.info(f"Saving combined audio to {temp_wav_file}")
        sf.write(temp_wav_file, w, text_to_speech.sample_rate)
        temp_mp3_file = f"/tmp/audio_{task_id}.mp3"
        logger.info(f"Converting WAV to MP3: {temp_mp3_file}")
        audio_segment = AudioSegment.from_wav(temp_wav_file)
        audio_segment.export(temp_mp3_file, format="mp3", parameters=["-q:a", "4"])
        del audio_segment  # Free memory after export
        file_size_bytes = os.path.getsize(temp_mp3_file)
        file_size_mb = file_size_bytes / (1024 * 1024)
        logger.info(f"MP3 file size: {file_size_mb:.2f} MB")
        if file_size_mb > 50:
            error_msg = f"MP3 file size ({file_size_mb:.2f} MB) exceeds Supabase free plan limit of 50 MB"
            logger.error(error_msg)
            if conversion_id:
                finalize_conversion(conversion_id, "", "failed", supabase=supabase)
            raise Exception(error_msg)

        update_conversion_progress(conversion_id, 85, supabase=supabase)

        # Upload MP3 file to Supabase storage
        logger.info("Uploading MP3 file to Supabase storage")
        with open(temp_mp3_file, "rb") as audio_file:
            audio_data = audio_file.read()

        # Generate output file path
        output_file_path = generate_output_file_path(file_info.user_id, file_info.file_name or "converted_audio")
        update_conversion_progress(conversion_id, 95, supabase=supabase)

        uploaded_path = upload_audio_file(output_file_path, audio_data, file_info.user_id, supabase=supabase)

        if uploaded_path:
            # Finalize the conversion record
            finalize_conversion(conversion_id, uploaded_path, "completed", supabase=supabase)
            logger.info(f"Audio file uploaded successfully: {uploaded_path}")
        else:
            logger.error("Failed to upload audio file")
            finalize_conversion(conversion_id, "", "failed", supabase=supabase)

        gc.collect()

        # Clean up temporary files
        if temp_wav_file and os.path.exists(temp_wav_file):
            os.remove(temp_wav_file)
        if temp_mp3_file and os.path.exists(temp_mp3_file):
            os.remove(temp_mp3_file)

        update_conversion_progress(conversion_id, 100, supabase=supabase)

        end = time.time()
        processing_time = end - start
        logger.info(f"Audio conversion completed in {processing_time:.2f} seconds")

        return {
            "status": "completed",
            "conversion_id": conversion_id,
            "output_file_path": uploaded_path,
            "processing_time": processing_time
        }

    except Exception as e:
        _status = 'failed'
        logger.error(f"Error in convert_to_audio_task: {str(e)}")
        # clean memory
        gc.collect()

        if conversion_id:
            try:
                # Update conversion record with error
                update_data = {
                    "status": "failed",
                    "job_completion": 0,
                    "error_message": str(e)
                }
                supabase.table("file_conversions").update(update_data).eq("conversion_id", conversion_id).execute()
            except:
                pass

        # Clean up temporary files
        if temp_wav_file and os.path.exists(temp_wav_file):
            try:
                os.remove(temp_wav_file)
            except:
                pass
        if temp_mp3_file and os.path.exists(temp_mp3_file):
            try:
                os.remove(temp_mp3_file)
            except:
                pass

        raise e
    finally:
        celery_tasks_total.labels(task_name='convert_to_audio_task', status=_status).inc()
        celery_task_duration_seconds.labels(task_name='convert_to_audio_task').observe(time.time() - _metric_start)


def _clean_for_tts(text: str) -> str:
    """Normalize text so supertonic produces clean speech.

    - Collapse newlines / carriage returns into spaces
    - Replace em dashes, en dashes, and hyphens used as separators with periods
    - Collapse multiple spaces / punctuation runs
    - Ensure exactly one capital letter at the start and nothing else uppercase
    """
    import re

    # Flatten newlines
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")

    # Replace dash-like separators (em dash, en dash, hyphen surrounded by spaces) with ". "
    text = re.sub(r'\s*[—–]\s*', '. ', text)
    text = re.sub(r'\s+-\s+', '. ', text)

    # Collapse runs of whitespace
    text = re.sub(r' {2,}', ' ', text).strip()

    # Collapse repeated punctuation / trailing punctuation before a period
    text = re.sub(r'[.!?,;:]{2,}', '.', text)

    # Lowercase everything, then capitalise the very first character
    text = text.lower()
    if text:
        text = text[0].upper() + text[1:]

    return text


@app.task()
def synthesize_sentence_task(text):
    temp_wav_file = None
    temp_mp3_file = None
    task_id = synthesize_sentence_task.request.id
    _metric_start = time.time()
    _status = 'success'
    try:
        cleaned = _clean_for_tts(text)
        print(f"[synthesize] original: {repr(text)}")
        print(f"[synthesize] cleaned:  {repr(cleaned)}")
        style = text_to_speech.get_voice_style("M3")
        wav, duration = text_to_speech.synthesize(cleaned, style, total_steps=5, speed=1.05, lang="en")
        w = wav[0, : int(text_to_speech.sample_rate * duration[0].item())]
        duration_secs = float(duration[0].item())

        temp_wav_file = f"/tmp/sentence_{task_id}.wav"
        sf.write(temp_wav_file, w, text_to_speech.sample_rate)

        temp_mp3_file = f"/tmp/sentence_{task_id}.mp3"
        audio_segment = AudioSegment.from_wav(temp_wav_file)
        audio_segment.export(temp_mp3_file, format="mp3", parameters=["-q:a", "4"])
        del audio_segment

        with open(temp_mp3_file, "rb") as f:
            audio_bytes = f.read()

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        logger.info(f"Synthesized sentence (original={len(text)} chars, cleaned={len(cleaned)} chars, {duration_secs:.2f}s)")
        return {"audio_b64": audio_b64, "duration": duration_secs}

    except Exception:
        _status = 'failed'
        raise
    finally:
        celery_tasks_total.labels(task_name='synthesize_sentence_task', status=_status).inc()
        celery_task_duration_seconds.labels(task_name='synthesize_sentence_task').observe(time.time() - _metric_start)
        if temp_wav_file and os.path.exists(temp_wav_file):
            os.remove(temp_wav_file)
        if temp_mp3_file and os.path.exists(temp_mp3_file):
            os.remove(temp_mp3_file)
