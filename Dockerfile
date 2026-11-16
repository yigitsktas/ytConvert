FROM python:3.12-slim

# ffmpeg: mp3 dönüşümü + video/ses birleştirme; nodejs: YouTube imza çözümü (yt-dlp)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py index.html favicon.ico ./

ENV PORT=10000
CMD gunicorn --bind 0.0.0.0:$PORT --worker-class gthread --threads 4 --timeout 900 app:app
