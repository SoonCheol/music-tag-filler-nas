FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY service.py .
RUN useradd --uid 10001 --create-home updater && mkdir -p /state && chown updater:updater /state
USER updater
EXPOSE 8766
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8766", "--workers", "1"]
