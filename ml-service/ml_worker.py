
import gc
import os
import time
from io import BytesIO
from chatterbox.tts import ChatterboxTTS
from celery import Celery
from doctr.io import DocumentFile
from doctr.models import ocr_predictor
import requests
import torchaudio as ta




rabbitmq_host = os.environ.get("RABBITMQ_HOST")
postgres_url = os.environ.get("DATABASE_CELERY_URL")
app = Celery(__name__, broker=f'pyamqp://guest@{rabbitmq_host}//', backend=postgres_url)
app.conf.update(broker_connection_retry_on_startup=True)

# Initialize the OCR predictor

@app.task()
def convert_file(file_url):
    start = time.time()
    import torch
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered
    # Handle file URLs and HTTP URLs differently
    if file_url.startswith("file://"):
        # Remove file:// prefix and load directly from file path
        file_path = file_url[7:-1]  # Remove "file://" prefix and trailing /
        print("loading file: ", file_path)
    else:
        raise NotImplementedError


    # Perform OCR
    converter = PdfConverter(
        artifact_dict=create_model_dict(),
    )
    res = converter(file_path)
    text, _, images = text_from_rendered(res)
    del converter
    gc.collect()
    torch.cuda.empty_cache()
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
    wavs = []
    tts_model = ChatterboxTTS.from_pretrained(device="cuda")
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
    del tts_model
    gc.collect()
    torch.cuda.empty_cache()
    return "OK"

