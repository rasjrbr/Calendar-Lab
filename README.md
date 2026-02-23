# Calendar Lab

Calendar Lab is a Docker-based pipeline that ingests an ICS calendar, applies custom parsing/normalization rules, and republishes a processed ICS feed.

## Components

- `postgres`: stores raw and processed calendar events.
- `worker`: runs ingestion/parsing/publishing Python jobs.
- `nginx`: serves generated ICS files.

Main paths:
- `worker/stages/`: active pipeline stages (numbered `s1_`–`s7_`).
- `worker/stages_optional/`: inactive/future stages.
- `worker/utils/`: shared utilities.
- `worker/config/`: reference data (JSON).
- `docs/`: architecture and cookbook notes.
- `docs/rulesets/`: aviation regulatory rule documentation.
- `docker-compose.yaml`: local orchestration.

## Quick Start

Prerequisites:

1. Create a public iFlight calendar WebCal link for the crewmember calendar.
2. Set `SOURCE_ICS_URL` in `docker-compose.yaml` to that link format:

```yaml
SOURCE_ICS_URL: webcal://crewmember-ics-from-iflight-calendar-public-link
```

From repo root, start the stack:

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

1. `stages/s1_ingest_ics.py` (if `SOURCE_ICS_URL` is set)
2. `stages/s2_init_parsing.py`
3. `stages/s3_checkout_creator.py`
4. `stages/s4_dayoff_parsing.py`
5. `stages/s5_dtl_singlecrew.py`
6. `stages/s6_dtl_hsb_rulecheck.py`
7. `stages/s7_publish_ics.py`

Optional/future stages in `worker/stages_optional/`:
- `activity_processor.py`
- `location_processor.py`
- `dtl_sc_ext.py`
- `overnight_check.py`

## Output

Generated calendars are written to `/var/www/calendars/{USER_ID}.ics` inside containers and served by nginx.

## Documentation

- Worker-focused guide: `worker/README.md`
- Detailed internal reference: `worker/AGENT.md`
- Architecture notes: `docs/ARCHITECTURE.md`
- Usage examples: `docs/COOKBOOK.md`
- Regulatory rulesets: `docs/rulesets/`
