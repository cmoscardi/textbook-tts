from fastapi import FastAPI, Header, HTTPException, Depends, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from uuid import UUID
import base64
import logging
import time
import os
from typing import Annotated

from task_client import send_parse_task, send_convert_task, send_synthesize_task, send_ingest_email_task, client_app
from email_alerts import setup_email_logging, send_alert
from prometheus_fastapi_instrumentator import Instrumentator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
setup_email_logging()

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

@app.middleware("http")
async def alert_on_error_response(request: Request, call_next):
    response = await call_next(request)
    if response.status_code >= 400:
        subject = f"[ml-service] HTTP {response.status_code} {request.method} {request.url.path}"
        body = (
            f"Method : {request.method}\n"
            f"Path   : {request.url.path}\n"
            f"Query  : {request.url.query}\n"
            f"Status : {response.status_code}\n"
            f"Client : {request.client.host if request.client else 'unknown'}\n"
        )
        send_alert(subject, body)
    return response

Instrumentator().instrument(app).expose(app)

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


class SynthesizeRequest(BaseModel):
    text: str = Field(description="The sentence text to synthesize", max_length=2000)


class IngestEmailRequest(BaseModel):
    sender: str = Field(description="The email sender address")
    subject: str = Field(description="The email subject line")
    has_attachment: bool = Field(description="Whether a PDF attachment is present")
    attachment_base64: str | None = None
    attachment_filename: str | None = None
    text_body: str | None = None
    html_body: str | None = None




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


@app.post("/synthesize")
def synthesize(request: SynthesizeRequest, auth: RequireAuth):
    logger.info(f"Received synthesize request ({len(request.text)} chars)")
    fut = send_synthesize_task(request.text)
    logger.info(f"Created synthesize task with ID: {fut.id}")
    return {"task_id": fut.id}


@app.get("/synthesize/{task_id}")
def get_synthesis(task_id: str, auth: RequireAuth):
    from celery.result import AsyncResult
    result = AsyncResult(task_id, app=client_app)

    if result.state in ('PENDING', 'STARTED', 'RETRY'):
        return {"status": "processing"}
    elif result.state == 'SUCCESS':
        audio_bytes = base64.b64decode(result.result["audio_b64"])
        duration = result.result.get("duration", 0)
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={"X-Audio-Duration": str(duration)},
        )
    else:  # FAILURE or REVOKED
        raise HTTPException(status_code=500, detail="Synthesis failed")


@app.post("/ingest-email")
def ingest_email(request: IngestEmailRequest, auth: RequireAuth):
    logger.info(f"Received ingest-email request from sender: {request.sender}")

    try:
        fut = send_ingest_email_task(request.model_dump())
        logger.info(f"Created ingest-email task with ID: {fut.id} for sender: {request.sender}")
        return {"id": fut.id, "task_type": "ingest_email"}
    except Exception as e:
        logger.error(f"Error creating ingest-email task for sender {request.sender}: {str(e)}")
        raise
