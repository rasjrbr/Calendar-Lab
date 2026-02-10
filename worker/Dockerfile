FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# code
COPY publish_ics.py /app/publish_ics.py
COPY worker_loop.py /app/worker_loop.py
COPY ingest_ics.py /app/ingest_ics.py


CMD ["python", "/app/worker_loop.py"]
