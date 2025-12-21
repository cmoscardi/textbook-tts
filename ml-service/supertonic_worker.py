import os
import gc
import logging
from celery import Celery
import time

import worker_utils as wu
from worker_utils import (
    get_file_info,
    get_parsed_text,
    create_conversion_record,
    update_conversion_progress,
    finalize_conversion,
    upload_audio_file,
    generate_output_file_path
)
from supertonic_utils import load_text_to_speech, timer, sanitize_filename, load_voice_style
import soundfile as sf

from pydub import AudioSegment
import torch

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

rabbitmq_host = os.environ.get("RABBITMQ_HOST")
postgres_url = os.environ.get("DATABASE_CELERY_URL")
logger.info(f"Initializing Celery with RabbitMQ host: {rabbitmq_host}")

supabase = wu.initialize_supabase()

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
        'supertonic_converter.convert_to_audio_task': {'queue': 'convert_queue'},
    },
)

logger.info("Loading tts...")
text_to_speech = load_text_to_speech("/supertonic/assets/onnx", use_gpu=False)

@app.task()
def convert_to_audio_task(file_id):
    start = time.time()
    task_id = convert_to_audio_task.request.id
    conversion_id = None
    temp_wav_file = None
    temp_mp3_file = None
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

        # Check if CUDA devices are available
        # if not torch.cuda.is_available():
        #     logger.warning("No CUDA device available - returning dev mode message")
        #     if conversion_id:
        #         finalize_conversion(conversion_id, "test.mp3", "completed", supabase=supabase)
        #     return "no cuda device -- dev mode"

        logger.info("CUDA device available, proceeding with TTS conversion")

        update_conversion_progress(conversion_id, 10, "running", supabase=supabase)
        logger.info("Loading supertonic style")

        style = load_voice_style(["/supertonic/assets/voice_styles/M2.json"], verbose=True)
        logger.info("Running TTS...")
        wav, duration = text_to_speech(parsed_text, style, 15, 1.05)
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

        # Cleanup intermediate results only (NOT the singleton model)
        logger.info("Cleaning up intermediate audio data (keeping singleton)")
        gc.collect()
        torch.cuda.empty_cache()

        logger.info(f"GPU memory after cleanup: allocated={torch.cuda.memory_allocated() / 1024**3:.2f} GB")

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
