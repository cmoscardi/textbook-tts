from supabase import create_client, Client
import os
from collections import namedtuple
import logging
import torch

FileInfo = namedtuple('FileInfo', ['signed_url', 'file_name', 'user_id'])

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def initialize_supabase():
    # Initialize Supabase client
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if supabase_url and supabase_key:
        supabase: Client = create_client(supabase_url, supabase_key)
        logger.info("Supabase client initialized")
    else:
        logger.warning("Supabase configuration missing - database operations will be disabled")
        supabase = None
    return supabase



def get_file_info(file_id: str, supabase: Client):
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


# Parsing helper functions
def create_parsing_record(file_id: str, job_id: str, supabase):
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


def update_parsing_progress(parsing_id: str, progress: int, status: str = None, supabase=None):
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


def finalize_parsing(parsing_id: str, file_id: str, parsed_text: str, status: str = "completed", raw_markdown: str = None, supabase=None):
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


# Conversion helper functions
def get_parsed_text(file_id: str, supabase):
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


def create_conversion_record(file_id: str, job_id: str, output_file_path: str = "", supabase=None):
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


def update_conversion_progress(conversion_id: str, progress: int, status: str = None, supabase=None):
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


def finalize_conversion(conversion_id: str, output_file_path: str, status: str = "completed", supabase=None):
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


# Storage helper functions
def upload_audio_file(file_path: str, file_data: bytes, user_id: str, content_type: str = "audio/mpeg", supabase=None):
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
    import uuid
    from datetime import datetime
    base_name = original_filename.rsplit(".", 1)[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    return f"{user_id}/{base_name}_{timestamp}_{unique_id}.mp3"
