import os
import gc
import logging
import base64
from celery import Celery
import time
import re

import numpy as np
import soundfile as sf
from pydub import AudioSegment

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

app = Celery(__name__, broker=f'pyamqp://guest@{rabbitmq_host}//', backend=postgres_url)

# Celery configuration for long-running TTS tasks
app.conf.update(
    broker_heartbeat=0,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=None,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=600,  # 10 minutes soft limit
    task_time_limit=900,  # 15 minutes hard limit
    result_expires=300,  # 5 minutes

    task_routes={
        'kitten_worker.convert_to_audio_task': {'queue': 'convert_queue'},
        'kitten_worker.synthesize_sentence_task': {'queue': 'synthesize_queue'},
    },
)
register_celery_failure_handler(app)

# KittenTTS configuration
KITTEN_MODEL = "KittenML/kitten-tts-micro-0.8"
KITTEN_VOICE = os.environ.get("KITTEN_VOICE", "Bruno")
KITTEN_SAMPLE_RATE = 24000

logger.info(f"Loading KittenTTS model: {KITTEN_MODEL} (voice: {KITTEN_VOICE})...")
from kittentts import KittenTTS
tts_model = KittenTTS(KITTEN_MODEL)
logger.info("KittenTTS model loaded successfully")


def silence(seconds, sr=KITTEN_SAMPLE_RATE):
    """Generate silence as a numpy array."""
    return np.zeros(int(seconds * sr), dtype=np.float32)


def split_text_into_chunks(text, max_chars=500):
    """Split text into chunks suitable for TTS generation.

    Splits on sentence boundaries (. ! ?) to keep chunks natural-sounding,
    staying under max_chars per chunk.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if not sentence.strip():
            continue
        if current_chunk and len(current_chunk) + len(sentence) + 1 > max_chars:
            chunks.append(current_chunk.strip())
            current_chunk = sentence
        else:
            current_chunk = current_chunk + " " + sentence if current_chunk else sentence

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


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
        if not parsed_text:
            logger.error(f"No parsed text found for file_id: {file_id}. Run /parse first.")
            return {"error": "No parsed text found. Please parse the PDF first."}

        logger.info(f"Retrieved parsed text ({len(parsed_text)} characters)")

        # Create conversion record in database
        conversion_id = create_conversion_record(file_id, task_id, supabase=supabase)
        if not conversion_id:
            logger.warning("Could not create conversion record - continuing without database tracking")

        update_conversion_progress(conversion_id, 10, "running", supabase=supabase)

        # Split text into chunks for TTS generation
        chunks = split_text_into_chunks(parsed_text)
        logger.info(f"Split text into {len(chunks)} chunks for TTS generation")

        # Generate audio for each chunk
        audio_segments = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Generating audio for chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
            audio = tts_model.generate(chunk, voice=KITTEN_VOICE)
            audio_segments.append(audio)
            audio_segments.append(silence(0.75))

            # Update progress (10% to 80% range for generation)
            progress = 10 + int((i + 1) / len(chunks) * 70)
            update_conversion_progress(conversion_id, progress, supabase=supabase)

        # Concatenate all audio
        combined_audio = np.concatenate(audio_segments, axis=0)
        duration_secs = len(combined_audio) / KITTEN_SAMPLE_RATE
        logger.info(f"Generated {duration_secs:.1f}s of audio")

        temp_wav_file = f"/tmp/audio_{task_id}.wav"
        logger.info(f"Saving combined audio to {temp_wav_file}")
        sf.write(temp_wav_file, combined_audio, KITTEN_SAMPLE_RATE)

        temp_mp3_file = f"/tmp/audio_{task_id}.mp3"
        logger.info(f"Converting WAV to MP3: {temp_mp3_file}")
        audio_segment = AudioSegment.from_wav(temp_wav_file)
        audio_segment.export(temp_mp3_file, format="mp3", parameters=["-q:a", "4"])
        del audio_segment
        del combined_audio

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

        output_file_path = generate_output_file_path(file_info.user_id, file_info.file_name or "converted_audio")
        update_conversion_progress(conversion_id, 95, supabase=supabase)

        uploaded_path = upload_audio_file(output_file_path, audio_data, file_info.user_id, supabase=supabase)

        if uploaded_path:
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
        gc.collect()

        if conversion_id:
            try:
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


@app.task()
def synthesize_sentence_task(text):
    temp_wav_file = None
    temp_mp3_file = None
    task_id = synthesize_sentence_task.request.id
    _metric_start = time.time()
    _status = 'success'
    try:
        audio = tts_model.generate(text, voice=KITTEN_VOICE)
        duration_secs = len(audio) / KITTEN_SAMPLE_RATE

        temp_wav_file = f"/tmp/sentence_{task_id}.wav"
        sf.write(temp_wav_file, audio, KITTEN_SAMPLE_RATE)

        temp_mp3_file = f"/tmp/sentence_{task_id}.mp3"
        audio_segment = AudioSegment.from_wav(temp_wav_file)
        audio_segment.export(temp_mp3_file, format="mp3", parameters=["-q:a", "4"])
        del audio_segment

        with open(temp_mp3_file, "rb") as f:
            audio_bytes = f.read()

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        logger.info(f"Synthesized sentence ({len(text)} chars, {duration_secs:.2f}s)")
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
