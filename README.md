# Calendar Lab

Calendar Lab is a Docker-based pipeline that ingests an ICS calendar, applies custom parsing/normalization rules, and republishes a processed ICS feed.

## Components

- `postgres`: stores raw and processed calendar events.
- `worker`: runs ingestion/parsing/publishing Python jobs.
- `nginx`: serves generated ICS files.

Main paths:
- `worker/`: pipeline code.
- `docs/`: architecture and cookbook notes.
- `docker-compose.yaml`: local orchestration.

## Quick Start

From repo root:

```bash
docker compose up -d --build
```

Check status:

```bash
docker compose ps
```

View worker logs:

```bash
docker compose logs -f worker
```

## Processing Flow

The default worker loop (`worker/worker_loop.py`) runs:

1. `ingest_ics.py` (if `SOURCE_ICS_URL` is set)
2. `init_parsing.py`
3. `checkout_creator.py`
4. `dayoff_parsing.py`
5. `publish_ics.py`

Optional/manual stages include:
- `activity_processor.py`
- `location_processor.py`
- `dtl-singlecrew.py`
- `dtl-sc-ext.py`

## Output

Generated calendars are written to `/var/www/calendars/{USER_ID}.ics` inside containers and served by nginx.

## Documentation

- Worker-focused guide: `worker/README.md`
- Detailed internal reference: `worker/AGENT.md`
- Architecture notes: `docs/ARCHITECTURE.md`
- Usage examples: `docs/COOKBOOK.md`

