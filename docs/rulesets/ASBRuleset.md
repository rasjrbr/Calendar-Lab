# ASB Processing Ruleset

## Scope
This document describes how ASB (standby) events are processed in the current Calendar Lab pipeline.

Date baseline: 2026-02-23.

## Active Pipeline
Default worker loop order:
1. `ingest_ics.py`
2. `init_parsing.py`
3. `checkout_creator.py`
4. `dayoff_parsing.py`
5. `dtl-singlecrew.py`
6. `dtl-hsb-rulecheck.py`
7. `publish_ics.py`

ASB handling starts in `init_parsing.py` and affects later stages through overlap guards.

## Source Input
ASB normally arrives in source summaries such as:
- `Activity : ASB`
- `Activity : ASB at CGH`

All source rows are first stored in `raw_events` with original `summary` and `description`.

## Core ASB Normalization (init_parsing.py)
### 1) Standby detection for overlap windows
- Any raw event with `ASB` or `HSB` in summary is treated as standby for overlap checks.
- This is used to delete conflicting `Report Time` rows before they become `Apresentação`.

### 2) ASB title conversion
- If title contains `ASB`, parser converts it to:
  - `Reserva em <CODE>` when location is found.
  - `Reserva` when location is not found.

### 3) Location extraction
Location priority:
1. Title pattern `ASB at XXX` (2-4 uppercase letters).
2. First line of notes with route pattern `XXX-YYY` (first code is used).
3. Fallback: no code.

When location is extracted:
- `location_code` is set.
- `location_details` is loaded from `lookup_homebases` if available.

### 4) Type and URL assignment
When ASB conversion happens:
- `event_type` is forced to `RESERVA`.
- `event_url` is set to the Reserva form URL.
- `#roquescript-modified` metadata is appended to notes.

## Overlap Rule: Report Time vs ASB/HSB
Before a `Report Time` row is converted to `Apresentação`, parser checks overlap against standby windows.

If overlap exists:
- Raw row is marked with `skip_reason = report_time_overlap_with_standby`.
- Any existing processed chain for that UID is deleted, including known synthetic children.

This prevents invalid duty chains from standby windows.

## Deduplication Interactions
ASB rows also pass through normal dedupe logic:
- Same-cycle dedupe (`duplicate_event_content`).
- Existing-row dedupe (`duplicate_event_existing`).

Important behavior:
- If two rows normalize to the same `(clean_title, start_utc, end_utc)`, whichever is processed first is kept.

## Downstream Guards (after parsing)
### checkout_creator.py
- Loads standby windows from non-synthetic `Reserva*`/`Sobreaviso`.
- If an `Apresentação` overlaps standby, Checkout is skipped and stale checkout is deleted.

### dtl-singlecrew.py
- Uses same standby overlap logic.
- If overlap exists, DTL markers are skipped/cleared for that duty chain.

## Publish Behavior (publish_ics.py)
For ASB-converted events (`event_type = RESERVA` or title starts with `Reserva`):
- Event is published with `clean_title`.
- Reserva reminder alarm is added (`-5m`).
- If location was resolved, `LOCATION` is populated (address/name/code fallback).
- If URL exists, it is published in event `URL`.

## Operational Notes
1. There is no global skip rule for `#roquescript` text in source notes.
2. Source-emitted synthetic-like titles (`Checkout`, `Final de Jornada`, `Horário Corte`) are dropped in parsing.
3. Current HSB checker is `dtl-hsb-rulecheck.py`; legacy `hsb-ruleset*.py` files were removed.

## Quick Verification Queries
Check ASB rows and their processed mapping:
```bash
docker compose exec -T postgres psql -U calendar -d calendardb -P pager=off -c "
SELECT r.source_uid, r.start_utc, r.summary, r.skip_reason, p.clean_title, p.event_type, p.location_code, p.event_url
FROM raw_events r
LEFT JOIN processed_events p ON p.user_id=r.user_id AND p.source_uid=r.source_uid
WHERE r.user_id='roque' AND r.summary ILIKE '%ASB%'
ORDER BY r.start_utc DESC;"
```

Check `Apresentação` removed due to standby overlap:
```bash
docker compose exec -T postgres psql -U calendar -d calendardb -P pager=off -c "
SELECT source_uid, start_utc, end_utc, summary, skip_reason
FROM raw_events
WHERE user_id='roque' AND skip_reason='report_time_overlap_with_standby'
ORDER BY start_utc DESC;"
```
