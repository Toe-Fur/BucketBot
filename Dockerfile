# Base Image
FROM python:3.11-slim
LABEL version="3.1"
LABEL description="Lowe's Scheduler Bot - Improved Reliability"


# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies
# - wget, gnupg, unzip: for downloading chrome
# - tesseract-ocr: for captcha/ocr
# - chromium, chromium-driver: for Selenium
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    tesseract-ocr \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY lowes_schedule_bot.py .
COPY google_calendar_diff_utils.py .

# Create data directory
RUN mkdir -p data

# Run the bot
CMD ["python", "-u", "lowes_schedule_bot.py"]
