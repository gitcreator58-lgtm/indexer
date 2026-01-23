FROM python:3.10-slim

WORKDIR /app

# Install ffmpeg (needed for yt-dlp)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

# Tell Docker that the container listens on this port
EXPOSE 8080

# Set default environment variable for PORT
ENV PORT=8080

CMD ["python", "bot.py"]
