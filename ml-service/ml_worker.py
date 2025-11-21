
import gc
import logging
import os
import time
import uuid
from collections import namedtuple
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

# Celery configuration for long-running GPU tasks
app.conf.update(
    broker_heartbeat=0,  # Disable heartbeat timeout for long-running tasks
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=None,  # Unlimited reconnection attempts
    task_acks_late=True,  # Only acknowledge task after it completes
    worker_prefetch_multiplier=1,  # Only fetch one task at a time (important for GPU)
    task_soft_time_limit=600,  # 10 minutes soft limit
    task_time_limit=900,  # 15 minutes hard limit
)

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

# Named tuple for file information
FileInfo = namedtuple('FileInfo', ['signed_url', 'file_name', 'user_id'])


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


# Parsing helper functions
def create_parsing_record(file_id: str, job_id: str):
    """Create a new file parsing record in the database"""
    if not supabase:
        logger.warning("Supabase not available - skipping database operation")
        return None

    try:
        data = {
            "file_id": file_id,
            "job_id": job_id,
            "job_completion": 0,
            "status": "pending"
        }
        result = supabase.table("file_parsings").insert(data).execute()
        logger.info(f"Created parsing record with ID: {result.data[0]['parsing_id']}")
        return result.data[0]['parsing_id']
    except Exception as e:
        logger.error(f"Failed to create parsing record: {e}")
        return None


def update_parsing_progress(parsing_id: str, progress: int, status: str = None):
    """Update the progress and status of a parsing job"""
    if not supabase or not parsing_id:
        return False

    try:
        update_data = {"job_completion": progress}
        if status:
            update_data["status"] = status

        supabase.table("file_parsings").update(update_data).eq("parsing_id", parsing_id).execute()
        logger.info(f"Updated parsing {parsing_id}: progress={progress}, status={status}")
        return True
    except Exception as e:
        logger.error(f"Failed to update parsing progress: {e}")
        return False


def finalize_parsing(parsing_id: str, file_id: str, parsed_text: str, status: str = "completed", raw_markdown: str = None):
    """Finalize a parsing job and update the files table with parsed text and raw markdown"""
    if not supabase or not parsing_id:
        return False

    try:
        # Update parsing record
        parsing_update = {
            "job_completion": 100,
            "status": status
        }
        supabase.table("file_parsings").update(parsing_update).eq("parsing_id", parsing_id).execute()

        # Update files table with parsed text and raw markdown
        if status == "completed" and parsed_text:
            files_update = {
                "parsed_text": parsed_text,
                "parsed_at": "NOW()"
            }
            # Add raw markdown if provided
            if raw_markdown:
                files_update["raw_markdown"] = raw_markdown

            supabase.table("files").update(files_update).eq("file_id", file_id).execute()
            logger.info(f"Finalized parsing {parsing_id} and updated file {file_id} with parsed text and raw markdown")
        else:
            logger.info(f"Finalized parsing {parsing_id} with status {status}")

        return True
    except Exception as e:
        logger.error(f"Failed to finalize parsing: {e}")
        return False


def get_parsed_text(file_id: str):
    """Get parsed text for a file

    Returns:
        str: Parsed text, or None if not available
    """
    if not supabase:
        logger.warning("Supabase not available - skipping database operation")
        return None

    try:
        result = supabase.table("files").select("parsed_text, parsed_at").eq("file_id", file_id).single().execute()

        if result.data and result.data.get('parsed_text'):
            logger.info(f"Retrieved parsed text for file {file_id}")
            return result.data['parsed_text']
        else:
            logger.warning(f"No parsed text found for file {file_id}")
            return None
    except Exception as e:
        logger.error(f"Failed to get parsed text: {e}")
        return None


def get_file_info(file_id: str):
    """Get file info and generate signed URL from file_id

    Returns:
        FileInfo: Named tuple with signed_url, file_name, and user_id, or None if failed
    """
    if not supabase:
        return None

    try:
        # Query the files table to get file metadata
        result = supabase.table("files").select("file_id, file_name, file_path, user_id").eq("file_id", file_id).execute()
        if not result.data:
            logger.error(f"No file found with file_id: {file_id}")
            return None

        file_data = result.data[0]
        file_name = file_data["file_name"]
        file_path = file_data["file_path"]
        user_id = file_data["user_id"]

        # Generate signed URL for the file (1 hour expiry)
        signed_url_result = supabase.storage.from_("files").create_signed_url(file_path, 3600)
        if not signed_url_result:
            logger.error(f"Failed to create signed URL for file_path: {file_path}")
            return None

        signed_url = signed_url_result.get("signedURL")
        logger.info(f"Generated signed URL for file_id: {file_id}")
        return FileInfo(signed_url=signed_url, file_name=file_name, user_id=user_id)

    except Exception as e:
        logger.error(f"Failed to get file info: {e}")
        return None


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


# Storage helper functions
def upload_audio_file(file_path: str, file_data: bytes, user_id: str, content_type: str = "audio/mpeg"):
    """Upload audio file to Supabase storage with correct owner"""
    if not supabase:
        logger.warning("Supabase not available - skipping file upload")
        return None

    try:
        # Upload the audio file
        logger.info(f"Uploading audio file: {file_path} for user: {user_id}")
        
        try:
            result = supabase.storage.from_("files").upload(
                path=file_path,
                file=file_data,
                file_options={
                    "content-type": content_type
                }
            )
        except Exception as upload_error:
            # If file already exists, try to update it instead
            if "already exists" in str(upload_error).lower():
                logger.info(f"File already exists, updating: {file_path}")
                result = supabase.storage.from_("files").update(
                    path=file_path,
                    file=file_data,
                    file_options={
                        "content-type": content_type
                    }
                )
            else:
                raise upload_error
        
        # Since we're using service role, we need to manually set the owner_id
        # by updating the storage.objects table directly
        logger.info(f"Setting owner_id for uploaded file: {file_path} to user: {user_id}")
        
        # Update the owner_id in the storage.objects table using raw SQL
        try:
            update_result = supabase.rpc("update_storage_owner", {
                "file_path": file_path,
                "bucket_name": "files", 
                "new_owner_id": user_id
            }).execute()
            
            if update_result.data:
                logger.info(f"Successfully updated owner_id for file: {file_path}")
            else:
                logger.warning(f"Could not update owner_id for file: {file_path}")
        except Exception as owner_error:
            logger.error(f"Failed to update owner_id for file {file_path}: {owner_error}")
            # Continue anyway - the file was uploaded successfully
        
        logger.info(f"Uploaded audio file: {file_path} with owner: {user_id}")
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
def parse_pdf_task(file_id):
    """Parse PDF and extract text, saving to database"""
    logger.info(f"Starting parse_pdf_task for file_id: {file_id}")

    # Get the current task ID
    task_id = parse_pdf_task.request.id
    parsing_id = None
    temp_file = None

    try:
        # Get file information and signed URL
        file_info = get_file_info(file_id)
        if not file_info:
            logger.error(f"Could not get file information for file_id: {file_id}")
            return {"error": "Invalid file_id or file not found"}

        # Create parsing record in database
        parsing_id = create_parsing_record(file_id, task_id)
        if not parsing_id:
            logger.warning("Could not create parsing record - continuing without database tracking")

        # Check if CUDA devices are available
        if not torch.cuda.is_available():
            logger.warning("No CUDA device available - returning dev mode message")
            if parsing_id:
                finalize_parsing(parsing_id, file_id, "dev mode text", "completed")
            return "no cuda device -- dev mode"

        logger.info("CUDA device available, proceeding with parsing")
        update_parsing_progress(parsing_id, 10, "running")

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

        update_parsing_progress(parsing_id, 20)

        # Perform PDF parsing with marker-pdf
        logger.info("Initializing PDF converter and creating model dictionary")
        logger.info(f"GPU memory allocated before converter load: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
        converter = PdfConverter(
            artifact_dict=create_model_dict(),
        )
        update_parsing_progress(parsing_id, 25)

        logger.info("Starting PDF conversion")
        res = converter(temp_file)
        text, _, images = text_from_rendered(res)
        logger.info(f"PDF conversion complete, extracted {len(text)} characters")
        update_parsing_progress(parsing_id, 40)

        # Cleanup converter resources
        logger.info("Cleaning up PDF converter resources")

        # Move converter to CPU before deletion to ensure GPU memory is released
        try:
            converter.cpu()
            if hasattr(converter, 'clear_cache'):
                converter.clear_cache()
        except Exception as e:
            logger.warning(f"Error moving converter to CPU: {e}")

        # Delete all intermediate results that might hold GPU tensors
        del converter
        del res
        if images:
            del images

        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.empty_cache()  # Call twice to help with fragmentation
        logger.info(f"GPU memory allocated after cleanup: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
        update_parsing_progress(parsing_id, 65)

        # Store original raw markdown
        raw_markdown = text
        logger.info(f"Stored raw markdown ({len(raw_markdown)} characters)")

        # Clean markdown for TTS
        logger.info("Cleaning markdown for TTS")
        cleaned_text = clean_markdown_for_tts(text)
        logger.info(f"Cleaned text for TTS ({len(cleaned_text)} characters)")
        update_parsing_progress(parsing_id, 75)

        # Text preprocessing - split into sentences
        import re
        sentences = re.split(r'(?<=[.!?]) +', cleaned_text)
        logger.info(f"Split text into {len(sentences)} sentences")

        # Save the parsed text (cleaned version)
        parsed_text = cleaned_text
        update_parsing_progress(parsing_id, 90)

        # Save to database (both raw markdown and cleaned text)
        logger.info(f"Saving parsed text and raw markdown to database")
        finalize_parsing(parsing_id, file_id, parsed_text, "completed", raw_markdown=raw_markdown)
        update_parsing_progress(parsing_id, 100)

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
            if 'converter' in locals():
                # Move converter to CPU before deletion to ensure GPU memory is released
                try:
                    converter.cpu()
                    if hasattr(converter, 'clear_cache'):
                        converter.clear_cache()
                except Exception as cleanup_err:
                    logger.warning(f"Error moving converter to CPU during error cleanup: {cleanup_err}")

                del converter

            # Clean up any other intermediate results that might hold GPU tensors
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
            torch.cuda.empty_cache()  # Call twice for fragmentation
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


@app.task()
def convert_to_audio_task(file_id):
    """Convert parsed text to audio using TTS"""
    logger.info(f"Starting convert_to_audio_task for file_id: {file_id}")

    # Get the current task ID
    task_id = convert_to_audio_task.request.id
    conversion_id = None
    temp_wav_file = None
    temp_mp3_file = None

    try:
        # Get file information for user_id and file_name
        file_info = get_file_info(file_id)
        if not file_info:
            logger.error(f"Could not get file information for file_id: {file_id}")
            return {"error": "Invalid file_id or file not found"}

        # Get parsed text from database
        parsed_text = get_parsed_text(file_id)
        if not parsed_text:
            logger.error(f"No parsed text found for file_id: {file_id}. Run /parse first.")
            return {"error": "No parsed text found. Please parse the PDF first."}

        logger.info(f"Retrieved parsed text ({len(parsed_text)} characters)")

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

        logger.info("CUDA device available, proceeding with TTS conversion")
        update_conversion_progress(conversion_id, 10, "running")

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

        # Split text into sentences for TTS processing
        import re
        sentences = re.split(r'(?<=[.!?]) +', parsed_text)
        logger.info(f"Split text into {len(sentences)} sentences for TTS processing")
        del parsed_text  # Free memory early - no longer needed
        update_conversion_progress(conversion_id, 20)

        # Initialize TTS model
        wavs = []
        logger.info("Loading ChatterboxTTS model on CUDA")
        logger.info(f"GPU memory before model load: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
        tts_model = ChatterboxTTS.from_pretrained(device="cuda")
        logger.info(f"GPU memory after model load: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
        update_conversion_progress(conversion_id, 30)

        # Generate audio for each sentence
        logger.info("Starting TTS generation for all sentences")
        # Use inference_mode to disable gradient tracking and reduce memory overhead
        with torch.inference_mode():
            for i, sentence in enumerate(sentences):
                if i % 10 == 0:  # Log progress every 10 sentences
                    logger.info(f"Processing sentence {i+1}/{len(sentences)}")

                # Update progress from 30% to 70% during TTS processing
                progress = 30 + int(((i + 1) / len(sentences)) * 40)
                update_conversion_progress(conversion_id, progress)

                # Move generated audio to CPU immediately to free GPU memory
                wav = tts_model.generate(sentence)
                wavs.append(wav.cpu())

                # Clear CUDA cache periodically during generation
                if i % 10 == 0:
                    torch.cuda.empty_cache()

        logger.info("Combining audio segments")
        combined_audio = torch.cat(wavs, dim=1)  # Already on CPU
        del wavs  # Explicitly delete the list
        del sentences  # Free memory - no longer needed
        gc.collect()
        update_conversion_progress(conversion_id, 75)

        # Save sample rate before cleanup
        sample_rate = tts_model.sr

        # Save to temporary WAV file first
        temp_wav_file = f"/tmp/audio_{task_id}.wav"
        logger.info(f"Saving combined audio to {temp_wav_file}")
        ta.save(temp_wav_file, combined_audio, sample_rate)

        # Convert WAV to MP3
        temp_mp3_file = f"/tmp/audio_{task_id}.mp3"
        logger.info(f"Converting WAV to MP3: {temp_mp3_file}")
        audio_segment = AudioSegment.from_wav(temp_wav_file)
        audio_segment.export(temp_mp3_file, format="mp3", bitrate="192k")
        del audio_segment  # Free memory after export

        update_conversion_progress(conversion_id, 85)

        # Upload MP3 file to Supabase storage
        logger.info("Uploading MP3 file to Supabase storage")
        with open(temp_mp3_file, "rb") as audio_file:
            audio_data = audio_file.read()

        # Generate output file path
        output_file_path = generate_output_file_path(file_info.user_id, file_info.file_name or "converted_audio")
        update_conversion_progress(conversion_id, 95)

        uploaded_path = upload_audio_file(output_file_path, audio_data, file_info.user_id)
        del audio_data  # Free memory after upload

        if uploaded_path:
            # Finalize the conversion record
            finalize_conversion(conversion_id, uploaded_path, "completed")
            logger.info(f"Audio file uploaded successfully: {uploaded_path}")
        else:
            logger.error("Failed to upload audio file")
            finalize_conversion(conversion_id, "", "failed")

        # Cleanup - move model to CPU before deletion
        logger.info("Cleaning up TTS model resources")
        logger.info(f"GPU memory before cleanup: allocated={torch.cuda.memory_allocated() / 1024**3:.2f} GB, reserved={torch.cuda.memory_reserved() / 1024**3:.2f} GB")

        # Synchronize CUDA to ensure all operations are complete
        torch.cuda.synchronize()

        try:
            # Clear T3 model caches explicitly before moving to CPU
            # These caches hold GPU tensors that won't be freed by .cpu()
            if hasattr(tts_model.t3, '_speech_pos_embedding_cache'):
                del tts_model.t3._speech_pos_embedding_cache
            if hasattr(tts_model.t3, '_speech_embedding_cache'):
                del tts_model.t3._speech_embedding_cache
            if hasattr(tts_model.t3, 'backend_cache'):
                del tts_model.t3.backend_cache
            if hasattr(tts_model.t3, 'backend_cache_params'):
                del tts_model.t3.backend_cache_params
            if hasattr(tts_model.t3, 'cudagraph_wrapper'):
                del tts_model.t3.cudagraph_wrapper
            if hasattr(tts_model.t3, 'patched_model'):
                del tts_model.t3.patched_model

            # Move model components to CPU to release GPU memory
            # ChatterboxTTS is not a PyTorch module, so we need to move each component
            tts_model.t3.cpu()
            tts_model.s3gen.cpu()
            tts_model.ve.cpu()
            if tts_model.conds is not None:
                tts_model.conds.to('cpu')

            # Clear any model-specific caches if available
            if hasattr(tts_model, 'clear_cache'):
                tts_model.clear_cache()
        except Exception as e:
            logger.warning(f"Error moving model to CPU: {e}")

        del tts_model
        del combined_audio
        gc.collect()

        # Comprehensive CUDA cleanup
        torch.cuda.empty_cache()
        torch.cuda.empty_cache()  # Call twice for fragmentation
        torch.cuda.ipc_collect()  # Clean up inter-process shared memory
        torch.cuda.reset_peak_memory_stats()  # Reset peak memory stats
        torch.cuda.reset_accumulated_memory_stats()  # Reset accumulated stats

        logger.info(f"GPU memory after cleanup: allocated={torch.cuda.memory_allocated() / 1024**3:.2f} GB, reserved={torch.cuda.memory_reserved() / 1024**3:.2f} GB")

        # Clean up temporary files
        if temp_wav_file and os.path.exists(temp_wav_file):
            os.remove(temp_wav_file)
        if temp_mp3_file and os.path.exists(temp_mp3_file):
            os.remove(temp_mp3_file)

        update_conversion_progress(conversion_id, 100)

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

        # Cleanup on error
        try:
            logger.info(f"GPU memory before error cleanup: allocated={torch.cuda.memory_allocated() / 1024**3:.2f} GB, reserved={torch.cuda.memory_reserved() / 1024**3:.2f} GB")

            # Synchronize CUDA to ensure all operations are complete
            torch.cuda.synchronize()

            if 'tts_model' in locals():
                # Move model components to CPU before deletion to ensure GPU memory is released
                try:
                    # Clear T3 model caches explicitly before moving to CPU
                    # These caches hold GPU tensors that won't be freed by .cpu()
                    if hasattr(tts_model.t3, '_speech_pos_embedding_cache'):
                        del tts_model.t3._speech_pos_embedding_cache
                    if hasattr(tts_model.t3, '_speech_embedding_cache'):
                        del tts_model.t3._speech_embedding_cache
                    if hasattr(tts_model.t3, 'backend_cache'):
                        del tts_model.t3.backend_cache
                    if hasattr(tts_model.t3, 'backend_cache_params'):
                        del tts_model.t3.backend_cache_params
                    if hasattr(tts_model.t3, 'cudagraph_wrapper'):
                        del tts_model.t3.cudagraph_wrapper
                    if hasattr(tts_model.t3, 'patched_model'):
                        del tts_model.t3.patched_model

                    # ChatterboxTTS is not a PyTorch module, so we need to move each component
                    tts_model.t3.cpu()
                    tts_model.s3gen.cpu()
                    tts_model.ve.cpu()
                    if tts_model.conds is not None:
                        tts_model.conds.to('cpu')

                    if hasattr(tts_model, 'clear_cache'):
                        tts_model.clear_cache()
                except Exception as cleanup_err:
                    logger.warning(f"Error moving model to CPU during error cleanup: {cleanup_err}")

                del tts_model

            # Clean up any other GPU tensors and intermediate objects
            if 'combined_audio' in locals():
                del combined_audio
            if 'wavs' in locals():
                del wavs
            if 'sentences' in locals():
                del sentences
            if 'parsed_text' in locals():
                del parsed_text
            if 'audio_segment' in locals():
                del audio_segment
            if 'audio_data' in locals():
                del audio_data

            gc.collect()

            # Comprehensive CUDA cleanup
            torch.cuda.empty_cache()
            torch.cuda.empty_cache()  # Call twice for fragmentation
            torch.cuda.ipc_collect()  # Clean up inter-process shared memory
            torch.cuda.reset_peak_memory_stats()  # Reset peak memory stats
            torch.cuda.reset_accumulated_memory_stats()  # Reset accumulated stats

            logger.info(f"GPU memory after error cleanup: allocated={torch.cuda.memory_allocated() / 1024**3:.2f} GB, reserved={torch.cuda.memory_reserved() / 1024**3:.2f} GB")
        except Exception as cleanup_err:
            logger.warning(f"Error during GPU cleanup: {cleanup_err}")

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

