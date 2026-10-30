FROM python:3.11-slim

# Install system dependencies for OCR and image reading
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libzbar0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run the unified web server and bot
CMD ["python", "bot.py"]