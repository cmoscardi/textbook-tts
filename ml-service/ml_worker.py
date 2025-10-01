
import gc
import logging
import os
import time
import uuid
from io import BytesIO
from chatterbox.tts import ChatterboxTTS
from celery import Celery
from doctr.io import DocumentFile
from doctr.models import ocr_predictor
import requests
import torchaudio as ta
from supabase import create_client, Client
from pydub import AudioSegment




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
app.conf.update(broker_connection_retry_on_startup=True)

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
if supabase_url and supabase_key:
    supabase: Client = create_client(supabase_url, supabase_key)
    logger.info("Supabase client initialized")
else:
    logger.warning("Supabase configuration missing - database operations will be disabled")
    supabase = None

# Initialize the OCR predictor
import torch
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered


# Database helper functions
def create_conversion_record(file_id: str, job_id: str, output_file_path: str = ""):
    """Create a new file conversion record in the database"""
    if not supabase:
        logger.warning("Supabase not available - skipping database operation")
        return None

    try:
        data = {
            "file_id": file_id,
            "job_id": job_id,
            "file_path": output_file_path,
            "job_completion": 0,
            "status": "pending"
        }
        result = supabase.table("file_conversions").insert(data).execute()
        logger.info(f"Created conversion record with ID: {result.data[0]['conversion_id']}")
        return result.data[0]['conversion_id']
    except Exception as e:
        logger.error(f"Failed to create conversion record: {e}")
        return None


def update_conversion_progress(conversion_id: str, progress: int, status: str = None):
    """Update the progress and status of a conversion"""
    if not supabase or not conversion_id:
        return False

    try:
        update_data = {"job_completion": progress}
        if status:
            update_data["status"] = status

        supabase.table("file_conversions").update(update_data).eq("conversion_id", conversion_id).execute()
        logger.info(f"Updated conversion {conversion_id}: progress={progress}, status={status}")
        return True
    except Exception as e:
        logger.error(f"Failed to update conversion progress: {e}")
        return False


def finalize_conversion(conversion_id: str, output_file_path: str, status: str = "completed"):
    """Finalize a conversion with the output file path"""
    if not supabase or not conversion_id:
        return False

    try:
        update_data = {
            "file_path": output_file_path,
            "job_completion": 100,
            "status": status
        }
        supabase.table("file_conversions").update(update_data).eq("conversion_id", conversion_id).execute()
        logger.info(f"Finalized conversion {conversion_id}: {output_file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to finalize conversion: {e}")
        return False


def get_file_info(file_url: str):
    """Extract file_id from file URL and get file info"""
    if not supabase:
        return None, None

    try:
        # Extract file path from signed URL - this is a simplified approach
        # In practice, you might need to parse the URL more carefully
        if "files/" in file_url:
            # Extract the file path after 'files/'
            file_path = file_url.split("files/")[1].split("?")[0]

            # Query the files table to get file_id
            result = supabase.table("files").select("file_id, file_name").eq("file_path", file_path).execute()
            if result.data:
                return result.data[0]["file_id"], result.data[0]["file_name"]

        logger.warning(f"Could not extract file info from URL: {file_url}")
        return None, None
    except Exception as e:
        logger.error(f"Failed to get file info: {e}")
        return None, None


# Storage helper functions
def upload_audio_file(file_path: str, file_data: bytes, content_type: str = "audio/mpeg"):
    """Upload audio file to Supabase storage"""
    if not supabase:
        logger.warning("Supabase not available - skipping file upload")
        return None

    try:
        result = supabase.storage.from_("files").upload(
            path=file_path,
            file=file_data,
            file_options={"content-type": content_type}
        )
        logger.info(f"Uploaded audio file: {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"Failed to upload audio file: {e}")
        return None


def generate_output_file_path(user_id: str, original_filename: str) -> str:
    """Generate a unique output file path for the converted audio"""
    timestamp = int(time.time())
    base_name = os.path.splitext(original_filename)[0]
    return f"{user_id}/converted_{timestamp}_{base_name}.mp3"


@app.task()
def convert_file(file_url):
    logger.info(f"Starting convert_file task for URL: {file_url}")

    # Get the current task ID
    task_id = convert_file.request.id
    conversion_id = None

    try:
        # Extract file information from URL
        file_id, original_filename = get_file_info(file_url)
        if not file_id:
            logger.error("Could not extract file information from URL")
            return {"error": "Invalid file URL"}

        # Create conversion record in database
        conversion_id = create_conversion_record(file_id, task_id)
        if not conversion_id:
            logger.warning("Could not create conversion record - continuing without database tracking")

        # Check if CUDA devices are available
        if not torch.cuda.is_available():
            logger.warning("No CUDA device available - returning dev mode message")
            if conversion_id:
                finalize_conversion(conversion_id, "test.mp3", "completed")
            return "no cuda device -- dev mode"

        logger.info("CUDA device available, proceeding with processing")
        update_conversion_progress(conversion_id, 10, "running")

        start = time.time()

        # Handle file URLs and HTTP URLs differently
        if file_url.startswith("file://"):
            # Remove file:// prefix and load directly from file path
            file_path = file_url[7:-1]  # Remove "file://" prefix and trailing /
            logger.info(f"Loading file from path: {file_path}")
        else:
            # For HTTP URLs, download the file first
            logger.info(f"Downloading file from URL: {file_url}")
            response = requests.get(file_url)
            response.raise_for_status()

            # Save to temporary file
            temp_file = f"/tmp/download_{task_id}.pdf"
            with open(temp_file, "wb") as f:
                f.write(response.content)
            file_path = temp_file
            logger.info(f"Downloaded file to: {file_path}")

        update_conversion_progress(conversion_id, 20)

        # Perform OCR
        logger.info("Initializing PDF converter and creating model dictionary")
        converter = PdfConverter(
            artifact_dict=create_model_dict(),
        )
        update_conversion_progress(conversion_id, 30)

        logger.info("Starting PDF conversion")
        res = converter(file_path)
        text, _, images = text_from_rendered(res)
        logger.info(f"PDF conversion complete, extracted {len(text)} characters")
        del converter
        gc.collect()
        torch.cuda.empty_cache()
        logger.info("Cleaned up PDF converter resources")
        update_conversion_progress(conversion_id, 50)

        # Save extracted text for reference
        logger.info("Writing extracted text to test-out.txt")
        with open("test-out.txt", "w+") as text_out_f:
            text_out_f.write(text)
            text_out_f.write("\n")

        def split_into_word_chunks(text, chunk_size=1024):
            words = text.split()  # split by any whitespace
            chunks = [
                " ".join(words[i:i + chunk_size])
                for i in range(0, len(words), chunk_size)
            ]
            return chunks

        chunks = split_into_word_chunks(text, chunk_size=100)
        import re
        sentences = re.split(r'(?<=[.!?]) +', text)
        logger.info(f"Split text into {len(sentences)} sentences for TTS processing")
        update_conversion_progress(conversion_id, 60)

        wavs = []
        logger.info("Loading ChatterboxTTS model on CUDA")
        tts_model = ChatterboxTTS.from_pretrained(device="cuda")
        update_conversion_progress(conversion_id, 70)

        logger.info("Starting TTS generation for all sentences")
        for i, sentence in enumerate(sentences):
            if i % 10 == 0:  # Log progress every 10 sentences
                logger.info(f"Processing sentence {i+1}/{len(sentences)}")
                # Update progress from 70% to 90% during TTS processing
                progress = 70 + int((i / len(sentences)) * 20)
                update_conversion_progress(conversion_id, progress)
            wavs.append(tts_model.generate(sentence))

        logger.info("Combining audio segments")
        combined_audio = torch.cat(wavs, dim=1)

        # Save to temporary WAV file first
        temp_wav_file = f"/tmp/audio_{task_id}.wav"
        logger.info(f"Saving combined audio to {temp_wav_file}")
        ta.save(temp_wav_file, combined_audio, tts_model.sr)

        # Convert WAV to MP3
        temp_mp3_file = f"/tmp/audio_{task_id}.mp3"
        logger.info(f"Converting WAV to MP3: {temp_mp3_file}")
        audio_segment = AudioSegment.from_wav(temp_wav_file)
        audio_segment.export(temp_mp3_file, format="mp3", bitrate="192k")

        update_conversion_progress(conversion_id, 90)

        # Upload MP3 file to Supabase storage
        logger.info("Uploading MP3 file to Supabase storage")
        with open(temp_mp3_file, "rb") as audio_file:
            audio_data = audio_file.read()

        # Generate output file path
        # Extract user_id from the file path (assuming format: user_id/filename)
        user_id = file_id.split('/')[0] if '/' in str(file_id) else 'unknown'
        output_file_path = generate_output_file_path(user_id, original_filename or "converted_audio")

        uploaded_path = upload_audio_file(output_file_path, audio_data)
        if uploaded_path:
            # Finalize the conversion record
            finalize_conversion(conversion_id, uploaded_path, "completed")
            logger.info(f"Audio file uploaded successfully: {uploaded_path}")
        else:
            logger.error("Failed to upload audio file")
            finalize_conversion(conversion_id, "", "failed")

        # Cleanup
        logger.info("Cleaning up TTS model resources")
        del tts_model
        gc.collect()
        torch.cuda.empty_cache()

        # Clean up temporary files
        if os.path.exists(temp_wav_file):
            os.remove(temp_wav_file)
        if os.path.exists(temp_mp3_file):
            os.remove(temp_mp3_file)
        if file_path.startswith("/tmp/download_"):
            os.remove(file_path)

        end = time.time()
        processing_time = end - start
        logger.info(f"Total processing time: {processing_time:.2f} seconds")

        logger.info("Task completed successfully")
        return {
            "status": "completed",
            "conversion_id": conversion_id,
            "output_file_path": uploaded_path,
            "processing_time": processing_time
        }

    except Exception as e:
        logger.error(f"Error in convert_file: {str(e)}")
        if conversion_id:
            finalize_conversion(conversion_id, "", "failed")

        # Cleanup on error
        try:
            if 'tts_model' in locals():
                del tts_model
                gc.collect()
                torch.cuda.empty_cache()
        except:
            pass

        raise e

