FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# code
COPY worker_loop.py /app/worker_loop.py
COPY ingest_ics.py /app/ingest_ics.py
COPY init_parsing.py /app/init_parsing.py
COPY init_lookup_tables.py /app/init_lookup_tables.py
COPY activity_processor.py /app/activity_processor.py
COPY checkout_creator.py /app/checkout_creator.py
COPY dayoff_parsing.py /app/dayoff_parsing.py
COPY location_processor.py /app/location_processor.py
COPY publish_ics.py /app/publish_ics.py
COPY schema.sql /app/schema.sql

# utilities
COPY utils/ /app/utils/

# config
COPY config/ /app/config/

CMD ["python", "/app/worker_loop.py"]
