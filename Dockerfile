
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# fpcalc + ffmpeg for fingerprint & cover convert
# Debian trixie 기준: fpcalc는 libchromaprint-tools 패키지에 포함
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libchromaprint-tools \
    && rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/fpcalc /usr/local/bin/fpcalc || true

WORKDIR /app
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock.txt

COPY app/ ./app/
WORKDIR /app

EXPOSE 8000

# MUSIC_ROOT=/music, DATA_ROOT=/data
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
