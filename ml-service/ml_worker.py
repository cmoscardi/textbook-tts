
import gc
import logging
import os
import time
from io import BytesIO
from chatterbox.tts import ChatterboxTTS
from celery import Celery
from doctr.io import DocumentFile
from doctr.models import ocr_predictor
import requests
import torchaudio as ta




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

# Initialize the OCR predictor
import torch
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered


@app.task()
def convert_file(file_url):
    logger.info(f"Starting convert_file task for URL: {file_url}")

    # Check if CUDA devices are available
    if not torch.cuda.is_available():
        logger.warning("No CUDA device available - returning dev mode message")
        return "no cuda device -- dev mode"

    logger.info("CUDA device available, proceeding with processing")
    start = time.time()
    # Handle file URLs and HTTP URLs differently
    if file_url.startswith("file://"):
        # Remove file:// prefix and load directly from file path
        file_path = file_url[7:-1]  # Remove "file://" prefix and trailing /
        logger.info(f"Loading file from path: {file_path}")
    else:
        logger.error(f"Unsupported URL format: {file_url}")
        raise NotImplementedError


    # Perform OCR
    logger.info("Initializing PDF converter and creating model dictionary")
    converter = PdfConverter(
        artifact_dict=create_model_dict(),
    )
    logger.info("Starting PDF conversion")
    res = converter(file_path)
    text, _, images = text_from_rendered(res)
    logger.info(f"PDF conversion complete, extracted {len(text)} characters")
    del converter
    gc.collect()
    torch.cuda.empty_cache()
    logger.info("Cleaned up PDF converter resources")
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

    wavs = []
    logger.info("Loading ChatterboxTTS model on CUDA")
    tts_model = ChatterboxTTS.from_pretrained(device="cuda")

    logger.info("Starting TTS generation for all sentences")
    for i, sentence in enumerate(sentences):
        if i % 10 == 0:  # Log progress every 10 sentences
            logger.info(f"Processing sentence {i+1}/{len(sentences)}")
        wavs.append(tts_model.generate(sentence))

    logger.info("Combining audio segments")
    combined_audio = torch.cat(wavs, dim=1)
    logger.info("Saving combined audio to test-1.wav")
    ta.save("test-1.wav", combined_audio, tts_model.sr)

    # If you want to synthesize with a different voice, specify the audio prompt
    #AUDIO_PROMPT_PATH="YOUR_FILE.wav"
    #wav = model.generate(text, audio_prompt_path=AUDIO_PROMPT_PATH)
    #ta.save("test-2.wav", wav, model.sr)
    end = time.time()
    processing_time = end - start
    logger.info(f"Total processing time: {processing_time:.2f} seconds")

    logger.info("Cleaning up TTS model resources")
    del tts_model
    gc.collect()
    torch.cuda.empty_cache()

    logger.info("Task completed successfully")
    return "OK"

