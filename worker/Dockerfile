FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# orchestrator and initialization
COPY worker_loop.py /app/worker_loop.py
COPY init_lookup_tables.py /app/init_lookup_tables.py
COPY schema.sql /app/schema.sql

# pipeline stages
COPY stages/ /app/stages/

# optional stages (available but not in default loop)
COPY stages_optional/ /app/stages_optional/

# utilities
COPY utils/ /app/utils/

# config
COPY config/ /app/config/

CMD ["python", "/app/worker_loop.py"]
