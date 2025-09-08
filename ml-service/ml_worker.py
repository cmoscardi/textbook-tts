
import os
from io import BytesIO
from chatterbox.tts import ChatterboxTTS
from celery import Celery
from doctr.io import DocumentFile
from doctr.models import ocr_predictor
import requests
import torch
import torchaudio as ta




rabbitmq_host = os.environ.get("RABBITMQ_HOST")
postgres_url = os.environ.get("DATABASE_CELERY_URL")
app = Celery(__name__, broker=f'pyamqp://guest@{rabbitmq_host}//', backend=postgres_url)
app.conf.update(broker_connection_retry_on_startup=True)

# Initialize the OCR predictor
device = torch.device('cuda')
predictor = ocr_predictor(pretrained=True).to(device)
tts_model = ChatterboxTTS.from_pretrained(device="cuda")

@app.task()
def convert_file(file_url):
    # Handle file URLs and HTTP URLs differently
    if file_url.startswith("file://"):
        # Remove file:// prefix and load directly from file path
        file_path = file_url[7:]  # Remove "file://" prefix
        doc = DocumentFile.from_pdf(file_path)
    else:
        # Handle HTTP/HTTPS URLs
        response = requests.get(pdf_url)
        response.raise_for_status()
        
        # Create a DocumentFile from the PDF bytes
        pdf_bytes = BytesIO(response.content)
        doc = DocumentFile.from_pdf(pdf_bytes)


    # Perform OCR
    result = predictor(doc)

    text = result.render().replace("\n", " ")
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
    wavs = []
    for sentence in sentences:
        wavs.append(tts_model.generate(sentence))
    combined_audio = torch.cat(wavs, dim=1)
    ta.save("test-1.wav", combined_audio, tts_model.sr)

    # If you want to synthesize with a different voice, specify the audio prompt
    #AUDIO_PROMPT_PATH="YOUR_FILE.wav"
    #wav = model.generate(text, audio_prompt_path=AUDIO_PROMPT_PATH)
    #ta.save("test-2.wav", wav, model.sr)
    end = time.time()
    print(end - start, "seconds elapsed")
    return "OK"

