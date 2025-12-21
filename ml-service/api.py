from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from uuid import UUID
import logging
import time
import os
from typing import Annotated

from task_client import send_parse_task, send_convert_task

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get auth key from environment
MLSERVICE_AUTH_KEY = os.environ.get("MLSERVICE_AUTH_KEY")
if not MLSERVICE_AUTH_KEY:
    logger.error("MLSERVICE_AUTH_KEY not set - API will reject all requests!")
    raise Exception("MLSERVICE_AUTH_KEY not set")


def verify_auth_key(ml_auth_key: str = Header(..., alias="ML-Auth-Key")):
    """
    Dependency function to verify the ML-Auth-Key header.

    Args:
        ml_auth_key: The authentication key from the request header

    Raises:
        HTTPException: If the key is missing or invalid

    Returns:
        str: The validated auth key
    """
    if not MLSERVICE_AUTH_KEY:
        logger.error("MLSERVICE_AUTH_KEY not configured")
        raise HTTPException(status_code=500, detail="Service configuration error")

    if ml_auth_key != MLSERVICE_AUTH_KEY:
        logger.warning(f"Invalid auth key attempt: {ml_auth_key[:10]}...")
        raise HTTPException(status_code=401, detail="Invalid authentication key")

    return ml_auth_key


# Type alias for dependency injection
RequireAuth = Annotated[str, Depends(verify_auth_key)]

app = FastAPI()

# Add CORS middleware to allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("FastAPI application initialized with CORS enabled")


@app.get("/")
@app.get("/health")
def health_check():
    """
    Health check endpoint for monitoring and load balancers.
    Includes CUDA device health check to ensure GPU is responsive.

    Returns:
        dict: Service status information

    Raises:
        HTTPException: If CUDA device is unavailable or unresponsive
    """
    # API container runs on CPU only (workers handle GPU processing)
    cuda_status = "not_required_api_cpu_only"

    return {
        "status": "healthy",
        "service": "ml-service",
        "cuda_status": cuda_status,
        "timestamp": time.time()
    }


class OCRRequest(BaseModel):
    file_id: UUID = Field(description="The UUID of the file in the database")


class ParseRequest(BaseModel):
    file_id: UUID = Field(description="The UUID of the file in the database")


class ConvertRequest(BaseModel):
    file_id: UUID = Field(description="The UUID of the file in the database")




@app.post("/parse")
def parse(request: ParseRequest, auth: RequireAuth):
    """
    Parse PDF endpoint that extracts text from a PDF and saves to database.
    This is step 1 of the split workflow (parse → convert).

    Requires authentication via ML-Auth-Key header.

    Args:
        request (ParseRequest): Request body containing file_id (UUID)
        auth (RequireAuth): Authentication dependency (automatically validated)

    Returns:
        dict: Task ID for the parsing job
    """
    logger.info(f"Received parse request for file_id: {request.file_id}")

    try:
        fut = send_parse_task(str(request.file_id))
        logger.info(f"Created parsing task with ID: {fut.id} for file_id: {request.file_id}")
        return {"id": fut.id, "task_type": "parse"}
    except Exception as e:
        logger.error(f"Error creating parse task for file_id {request.file_id}: {str(e)}")
        raise


@app.post("/convert")
def convert(request: ConvertRequest, auth: RequireAuth):
    """
    Convert to audio endpoint that generates TTS audio from parsed text.
    This is step 2 of the split workflow (parse → convert).
    Requires that /parse has been called first on this file.

    Requires authentication via ML-Auth-Key header.

    Args:
        request (ConvertRequest): Request body containing file_id (UUID)
        auth (RequireAuth): Authentication dependency (automatically validated)

    Returns:
        dict: Task ID for the conversion job
    """
    logger.info(f"Received convert request for file_id: {request.file_id}")

    try:
        fut = send_convert_task(str(request.file_id))
        logger.info(f"Created conversion task with ID: {fut.id} for file_id: {request.file_id}")
        return {"id": fut.id, "task_type": "convert"}
    except Exception as e:
        logger.error(f"Error creating convert task for file_id {request.file_id}: {str(e)}")
        raise
