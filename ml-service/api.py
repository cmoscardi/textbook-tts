from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, AnyUrl, Field
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
    pdf_url: AnyUrl = Field(description="URL where the PDF to be loaded is located (HTTP/HTTPS or file:// URLs supported)")



@app.post("/ocr")
def ocr(request: OCRRequest):
    """
    OCR endpoint that processes a PDF from a URL using docTR.

    Args:
        request (OCRRequest): Request body containing pdf_url (HTTP or file URL)

    Returns:
        dict: Task ID for the OCR job
    """
    logger.info(f"Received OCR request for URL: {request.pdf_url}")

    try:
        fut = convert_file.delay(str(request.pdf_url))
        logger.info(f"Created Celery task with ID: {fut.id}")
        return {"id": fut.id}
    except Exception as e:
        logger.error(f"Error creating OCR task: {str(e)}")
        raise
