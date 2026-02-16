# Calendar Lab Worker

Calendar Lab Worker ingests an ICS calendar, normalizes events in PostgreSQL, and publishes a processed ICS output.

## What It Does

- Pulls source events from `SOURCE_ICS_URL` into `raw_events`.
- Applies parsing rules to generate `processed_events`.
- Creates synthetic workflow events like `Checkout` and duty-limit markers.
- Removes day-off events based on config.
- Publishes final output as `OUT_DIR/{USER_ID}.ics`.

## Main Pipeline

Default loop in `worker_loop.py` runs every `INTERVAL_SECONDS` (default: 600):

1. `ingest_ics.py` (if `SOURCE_ICS_URL` is set)
2. `init_parsing.py`
3. `checkout_creator.py`
4. `dayoff_parsing.py`
5. `publish_ics.py`

Optional/manual stages:
- `activity_processor.py`
- `location_processor.py`
- `dtl-singlecrew.py`
- `dtl-sc-ext.py`

## Project Layout

- `ingest_ics.py`: ICS ingestion into `raw_events`.
- `init_parsing.py`: first normalization stage and core business rules.
- `checkout_creator.py`: synthetic `Checkout` generation.
- `dayoff_parsing.py`: day-off filtering.
- `dtl-singlecrew.py`: duty limit markers.
- `dtl-sc-ext.py`: duty extension markers.
- `publish_ics.py`: final ICS generation.
- `schema.sql`: PostgreSQL schema.
- `utils/`: DB, logging, timezone, notes helpers.
- `config/`: lookup JSON files.

## Quick Start (Docker Compose)

From repository root (one level above this folder):

```bash
docker compose up -d --build
```

Check service status:

```bash
docker compose ps
```

Tail worker logs:

```bash
docker compose logs -f worker
```

## Manual Run

Run a full one-shot processing pass:

```bash
docker compose exec -T worker sh -lc \
'python /app/init_parsing.py && \
 python /app/checkout_creator.py && \
 python /app/dayoff_parsing.py && \
 python /app/dtl-singlecrew.py && \
 python /app/dtl-sc-ext.py && \
 python /app/publish_ics.py'
```

## Key Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `USER_ID` | `roque` | Tenant/user key used in DB rows and output filename |
| `SOURCE_ICS_URL` | unset | Input ICS feed URL (`webcal://` supported) |
| `INTERVAL_SECONDS` | `600` | Loop interval in seconds |
| `OUT_DIR` | `/var/www/calendars` | Output directory for generated ICS |
| `DB_HOST` | `postgres` | PostgreSQL host |
| `DB_NAME` | `calendardb` | PostgreSQL DB name |
| `DB_USER` | `calendar` | PostgreSQL username |
| `DB_PASSWORD` | `calendarpass` | PostgreSQL password |
| `SOURCE_TZ` | `America/Sao_Paulo` | Source timezone for floating datetimes |

## Data Model (High Level)

- `raw_events`: source mirror + ingestion flags.
- `processed_events`: normalized and synthetic events used for publishing.
- `lookup_*`: reference tables.
- `*_pending_validation`: unknown activity/homebase queues.

## Notes and Metadata

Rules append roquescript metadata blocks into notes using:
- marker: `[--#roquescript-info-below-]`
- tags like `#roquescript-modified` and `#roquescript-created`.

## Additional Technical Reference

See `AGENT.md` for a deeper technical description, including a full `init_parsing.py` walkthrough and rule behavior.
