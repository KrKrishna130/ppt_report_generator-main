FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    OUTPUT_DIR=/app/generated \
    TMP_DIR=/app/tmp

WORKDIR /app

# PowerPoint -> PDF conversion, fonts, and PDF -> image conversion.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-impress \
    libreoffice-writer \
    libreoffice-calc \
    poppler-utils \
    fonts-liberation \
    fontconfig \
    ca-certificates \
    && fc-cache -f -v \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies separately for better build caching.
COPY requirements.txt /app/requirements.txt

RUN python -m pip install --upgrade pip \
    && pip install -r /app/requirements.txt

# Copy the application code.
COPY app/ /app/app/

# Create directories used by the application.
RUN mkdir -p /app/generated /app/tmp \
    && chmod -R 777 /app/generated /app/tmp

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
