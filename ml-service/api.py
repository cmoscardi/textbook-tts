from fastapi import FastAPI
from pydantic import BaseModel, AnyUrl, Field
import time

from ml_worker import app as celery_app
from ml_worker import convert_file

app = FastAPI()


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
    fut = convert_file.delay(str(request.pdf_url))
    return {"id": fut.id}
