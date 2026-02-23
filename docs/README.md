# Docs Index

This folder contains project-level technical notes and operational tracking.

## Files

- `ARCHITECTURE.md`: service and data-flow overview.
- `COOKBOOK.md`: operational commands and common procedures.
- `DEVLOG.md`: dated changelog with troubleshooting and fixes.
- `AGEND.md`: current agenda, open checks, and follow-up actions.

## Current Pipeline Snapshot

Default worker loop (`worker/worker_loop.py`) runs:

1. `ingest_ics.py` (if `SOURCE_ICS_URL` is set; cadence controlled by `INGEST_INTERVAL_SECONDS`, default 600s)
2. `init_parsing.py`
3. `checkout_creator.py`
4. `dayoff_parsing.py`
5. `dtl-singlecrew.py`
6. `dtl-hsb-rulecheck.py`
7. `publish_ics.py`

Loop sleep interval is `INTERVAL_SECONDS` (default 20s).
