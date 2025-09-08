#!/bin/bash
#
# now doctr
apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    git \

pip install librosa torchaudio resemble-perth safetensors transformers conformer s3tokenizer diffusers omegaconf
#pip install chatterbox-tts --no-dependencies
pip install git+https://github.com/rsxdalv/chatterbox.git@faster --no-dependencies


pip install python-doctr
pip install fastapi uvicorn[standard] python-multipart pydantic
pip install celery
