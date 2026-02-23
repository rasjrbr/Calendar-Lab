# 2026-02-21

## Pipeline: Duty Limit Stage Activation

- Updated `worker/worker_loop.py` to run `dtl-singlecrew.py` inside the default loop.
- Reordered stages so duty-limit markers are generated before publish:
  1. `ingest_ics.py` (when `SOURCE_ICS_URL` is set)
  2. `init_parsing.py`
  3. `checkout_creator.py`
  4. `dayoff_parsing.py`
  5. `dtl-singlecrew.py`
  6. `publish_ics.py`
- Reduced default worker loop interval from `600` seconds to `20` seconds.

## Commit

- Commit: `a55c85e`
- Message: `Run DTL before publish and shorten worker interval`
- Scope: `worker/worker_loop.py` only.

## Runtime Apply / Verification

- Restarted service: `calendar_worker` (`docker compose restart worker`).
- Verified in logs that `dtl-singlecrew` now executes before `publish_ics`.
- Confirmed one post-change cycle with:
  - `dtl-singlecrew complete: processed=74, markers_upserted=148`
  - `publish_ics complete: events_published=809`

# 2026-02-22

## Ingestion: Full Rebuild to Prevent Synthetic Duplicates

- Updated `worker/ingest_ics.py` to run in deterministic full-rebuild mode per sync cycle.
- New ingestion flow for one `user_id`:
  1. Parse latest source ICS payload.
  2. Clear all existing `processed_events` for the user.
  3. Clear all existing `raw_events` for the user.
  4. Insert only events from the latest source payload into `raw_events` with `processed_flag=FALSE`.
- Added duplicate UID guard within the same ICS payload (`duplicate-uids-skipped`) to avoid repeated inserts from malformed feeds.

## Why

- Incremental reconciliation allowed stale synthetic children (e.g. `-dtl-final`, `-dtl-cut-d`) to survive after source UID churn.
- Those stale synthetic rows accumulated and appeared as duplicate `Final de Jornada` / `Horário Corte` entries on refresh.

## Verification

- Ran one full manual cycle (`ingest_ics.py` -> `init_parsing.py` -> `checkout_creator.py` -> `dtl-singlecrew.py` -> `publish_ics.py`).
- Confirmed February 26 has a single duty-limit chain:
  - `Apresentação`
  - `Checkout`
  - `Horário Corte (d)`
  - `Final de Jornada`

# 2026-02-23

## Duplicate Chain Fix: Apresentacao -> Checkout -> Duty Markers

- Root cause identified: duplicated non-synthetic `Apresentação` events with different `source_uid` values were being accepted, which generated duplicated synthetic chains (`Checkout`, `Horário Corte`, `Final de Jornada`).
- Updated `worker/init_parsing.py` with cross-cycle deduplication:
  - New guard skips insertion when a non-synthetic event already exists for the same `(clean_title, start_utc, end_utc)`.
  - New `raw_events.skip_reason`: `duplicate_event_existing`.
- Kept same-cycle dedupe in place (`duplicate_event_content`) and source synthetic-title deletion rule in place.

## Data Cleanup and Regeneration

- Removed existing duplicated rows in `processed_events` for `roque` based on repeated non-synthetic `(clean_title, start_utc, end_utc)`, including synthetic children tied to removed source UIDs.
- Re-ran pipeline stages:
  1. `checkout_creator.py`
  2. `dayoff_parsing.py`
  3. `dtl-singlecrew.py`
  4. `dtl-hsb-rulecheck.py`
  5. `publish_ics.py`

## Verification

- Post-cleanup query returned zero duplicates for non-synthetic events grouped by `(clean_title, start_utc, end_utc)`.
- Repeated synthetic markers now correlate to unique source duties instead of duplicate source rows.
