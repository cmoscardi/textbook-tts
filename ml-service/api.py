from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from uuid import UUID
import logging
import time

from ml_worker import app as celery_app
from ml_worker import convert_file

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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


class OCRRequest(BaseModel):
    file_id: UUID = Field(description="The UUID of the file in the database")



@app.post("/ocr")
def ocr(request: OCRRequest):
    """
    OCR endpoint that processes a PDF using docTR.

    Args:
        request (OCRRequest): Request body containing file_id (UUID)

    Returns:
        dict: Task ID for the OCR job
    """
    logger.info(f"Received OCR request for file_id: {request.file_id}")

    try:
        fut = convert_file.delay(str(request.file_id))
        logger.info(f"Created Celery task with ID: {fut.id} for file_id: {request.file_id}")
        return {"id": fut.id}
    except Exception as e:
        logger.error(f"Error creating OCR task for file_id {request.file_id}: {str(e)}")
        raise
