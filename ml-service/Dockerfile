FROM pytorch/pytorch:2.8.0-cuda12.6-cudnn9-devel


# Install system dependencies
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    git \
    postgresql-client \
    libpq-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
RUN pip install librosa torchaudio resemble-perth safetensors transformers conformer s3tokenizer diffusers omegaconf

# Install chatterbox from git (no dependencies)
RUN pip install git+https://github.com/rsxdalv/chatterbox.git@faster --no-dependencies

# Install additional Python packages
RUN pip install python-doctr \
    fastapi uvicorn[standard] python-multipart pydantic \
    celery sqlalchemy psycopg2 \
    marker-pdf \
    jupyter watchdog \
    supabase \
    pydub

# Copy application code
COPY . .

# Default command (can be overridden)
CMD ["python", "-m", "celery", "worker", "-A", "ml_worker", "--loglevel=info"]
