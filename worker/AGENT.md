# Calendar Lab Worker: Agent Guide

This document summarizes the project architecture and gives a focused reference for `init_parsing.py`.

## 1. Project Purpose

Calendar Lab ingests a source ICS calendar, normalizes and enriches events in PostgreSQL, generates synthetic duty markers, and publishes a final ICS file.

Core goals:
- Keep source data in `raw_events`.
- Create normalized, automation-friendly `processed_events`.
- Track transformations with `modifications`, `tags`, and roquescript notes blocks.
- Publish a clean ICS for downstream calendar clients.

## 2. Runtime Topology

Services are defined in `../docker-compose.yaml`:
- `postgres`: state store.
- `worker`: Python pipeline container.
- `nginx`: serves published ICS from shared volume.

Worker image and entrypoint are in `Dockerfile` and `worker_loop.py`.

Default loop interval:
- `INTERVAL_SECONDS=600` (10 minutes) unless overridden by environment.

## 3. Current Automated Pipeline (worker_loop.py)

Every loop, the container runs:
1. `ingest_ics.py` (only if `SOURCE_ICS_URL` is set)
2. `init_parsing.py`
3. `checkout_creator.py`
4. `dayoff_parsing.py`
5. `publish_ics.py`

Not currently in the default loop (manual/on-demand):
- `activity_processor.py`
- `location_processor.py`
- `dtl-singlecrew.py`
- `dtl-sc-ext.py`

## 4. Data Model Summary

Defined in `schema.sql`.

Main tables:
- `raw_events`: immutable-ish source mirror + ingestion bookkeeping.
- `processed_events`: normalized canonical events + synthetic markers.

Important `processed_events` fields:
- `source_uid`: stable key used for idempotent upserts.
- `raw_event_id`: points back to source row.
- `event_type`, `clean_title`, `original_title`.
- `notes`, `notes_original`.
- `is_synthetic`.
- `modifications` (JSON array of rule applications).
- `tags` (JSON array; includes roquescript markers).

Auxiliary tables:
- `lookup_*` tables for day-off/homebase/activity lookups.
- `*_pending_validation` queues for unknown codes.
- `user_parsing_settings` for future day-off modes.

## 5. init_parsing.py Deep Dive

`init_parsing.py` is the first normalization stage and the most important transformation point.

### Input
- Reads `raw_events` where `processed_flag = FALSE` for one `user_id`.
- Orders rows by `start_utc`.

### High-level phases
1. Deletion checks.
2. Event-type classification.
3. Overlap rules for `Report Time`.
4. Title/notes modifications.
5. Upsert to `processed_events`.
6. Mark `raw_events.processed_flag = TRUE`.
7. Post-pass cleanup for standby/report-time conflicts.

### Deletion rules
- `Start Time:` events are deleted (`skip_reason = start_time_removed`).

Helper `delete_event_and_related_synthetics(...)` removes:
- Base processed event (`source_uid`)
- `-checkout-synthetic`
- `-dtl-final`
- `-dtl-cut-d`
- `-dtl-cut-i`
- `-dtl-sc-ext-1h`
- `-dtl-sc-ext-cut`

This keeps old synthetic artifacts from surviving when source logic changes.

### Classification
`classify_event_type(title)` returns:
- `REPORT_TIME` if title contains `Report Time`
- `ACTIVITY` if title contains `Activity`
- `FLIGHT` if title contains `Flight`
- else `UNKNOWN`

### Overlap safeguards (critical business rule)

#### A) Report Time vs standby windows (ASB/HSB)
- Standby windows are built from raw rows containing `ASB` or `HSB`.
- Any `Report Time` overlapping those windows is deleted with:
  - `skip_reason = report_time_overlap_with_standby`

This enforces:
- No Apresentação for Reserva/Sobreaviso windows.
- Therefore no Checkout/DTL should be generated from those conflicts.

#### B) Report Time vs Activity overlap
- Existing rule preserved:
  - `skip_reason = report_time_overlap_with_activity`.

### Modification rules

`apply_modifications(title, notes, event_type)` can transform:

- `HSB` -> `Sobreaviso`
  - Sets `special_flags["is_sobreaviso"] = True`.
  - Appends a `#roquescript #roquescript-modified` block.

- `ASB` -> `Reserva em XXX` (or `Reserva`)
  - Extracts location from title (`ASB at XXX`) or notes first line (`XXX-YYY`).
  - Sets `special_flags["is_reserva"] = True`.
  - Sets reservation form URL in `event_url`.
  - Appends roquescript block.

- `Activity : CODE` -> `CODE` and sets `activity_code`.
- `Flight : ...` -> strips `Flight :`.
- `Report Time ...` -> `Apresentação`.

If modifications occurred, tag `#roquescript-modified` is set.

### Final event_type adjustments
After modifications:
- If `is_reserva`: force `event_type = RESERVA`.
- If `is_sobreaviso`: force `event_type = SOBREAVISO`.

### Notes behavior
- Base notes come from source `description`.
- Every modification appends roquescript metadata blocks via `utils/notes_utils.py`:
  - marker: `[--#roquescript-info-below-]`

### Idempotency behavior
- Uses upsert on `(user_id, source_uid)`.
- Re-ingestion resets raw `processed_flag` for changed UIDs.
- `init_parsing` is safe to rerun.

### Post-pass cleanup
`cleanup_standby_report_time_conflicts(...)` scans already-processed rows and removes any `Apresentação` overlapping `Reserva`/`Sobreaviso`, even when no new raw rows are incoming.

This avoids stale historical conflicts.

## 6. Other Stages (Brief)

### ingest_ics.py
- Fetches ICS (`webcal://` converted to `https://`).
- Inserts/updates `raw_events`.
- Sets changed rows back to `processed_flag = FALSE`.
- Reconciles deleted UIDs (removes stale raw + processed copies).

### checkout_creator.py
- Builds synthetic `Checkout` from each valid `Apresentação`.
- Shortens `Apresentação` duration to 10 minutes.
- Defensive guard: if Apresentação overlaps Reserva/Sobreaviso, skip checkout and delete stale checkout.

### dayoff_parsing.py
- Deletes day-off/off-at events using config + patterns.
- Keeps scaffolding for future user-configurable dayoff modes.

### dtl-singlecrew.py
- Computes duty limit markers (`Final de Jornada`, `Horário Corte (d/i)`).
- Uses local BRT duty tables and leg classification.
- Guard: skips/clears DTL markers for Apresentação overlapping Reserva/Sobreaviso.
- Notes now follow roquescript-created format and preserve original source notes.

### dtl-sc-ext.py
- For recent duties only (last 2 days to today), adds extension markers if checkout exceeds final duty limit.
- Depends on existing checkout + cutoff markers.

### publish_ics.py
- Exports all `processed_events` to final ICS.
- Includes notes/tags in description and adds reminders:
  - Reserva: -5m
  - Checkout: -10m
  - Corte markers: -20m

## 7. Shared Utilities

- `utils/db_utils.py`: retrying DB connection + schema bootstrap.
- `utils/timezone_utils.py`: source timezone and UTC conversion.
- `utils/notes_utils.py`: roquescript notes block formatting.
- `utils/logging_utils.py`: JSON structured logs.

## 8. Practical Runbook

Manual full run in Docker:

```bash
docker compose -f ../docker-compose.yaml exec -T worker sh -lc \
'python /app/init_parsing.py && \
 python /app/checkout_creator.py && \
 python /app/dayoff_parsing.py && \
 python /app/dtl-singlecrew.py && \
 python /app/dtl-sc-ext.py && \
 python /app/publish_ics.py'
```

Default loop already running in `calendar_worker`:
- interval controlled by `INTERVAL_SECONDS`.

## 9. Current Known Design Notes

- `activity_processor.py` and `location_processor.py` exist but are not in `worker_loop.py` by default.
- Some older rows may still carry legacy `event_type` values (`UNKNOWN`/`ACTIVITY`) for standby titles created before newer rules; current rules now enforce `RESERVA`/`SOBREAVISO` for newly processed rows.
