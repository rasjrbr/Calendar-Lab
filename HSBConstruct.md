# HSB Construct Log

## Scope
Record of the HSB investigation and temporary implementation work done on **2026-02-18** for `roque`.

## Key Findings
1. `worker/hsb-ruleset.py` analyzes `processed_events` (normalized data), not raw iFlightNeo directly.
2. Duplicates in `roque.ics` were coming from the source feed itself (polluted upstream), not from `hsb-ruleset-dummy.py`.
3. Previous manual HSB runs had left synthetic rows (`Deslocamento`, `Violation!`) in `processed_events`.
4. Timezone conversion was correct; the initial overlap issue came from dummy scenario times not matching real day events.

## Pipeline State Confirmed
Current worker loop order (`worker/worker_loop.py`):
1. `ingest_ics.py`
2. `init_parsing.py`
3. `checkout_creator.py`
4. `dayoff_parsing.py`
5. `publish_ics.py`

HSB scripts are not in the loop.

## Changes Made
1. `worker/hsb-ruleset.py`
- Added safety gate: disabled unless `HSB_RULESET_ENABLED=1`.

2. `worker/hsb-ruleset-dummy.py`
- Updated travel rule:
  - `148` minutes for `GRU/CGH/GIG/SDU`
  - `88` minutes for other airports
- Added temporary DB/publish tooling:
  - `--apply-db`
  - `--publish-ics`
  - `--cleanup-only`
  - `--from-db-today`
  - `--from-db-date YYYY-MM-DD`
- Default remains dry-run (no DB writes).

3. Data cleanup executed
- Removed old HSB synthetic rows:
  - `%-hsb-deslocamento`
  - `%-hsb-violation-%`
- Republished ICS after cleanup.

## Validated Working Case (Real Day Input)
Using real events for **2026-02-18** with:
`python /app/hsb-ruleset-dummy.py --from-db-today --apply-db --publish-ics`

Published synthetic event:
- UID: `391A78C9-3E37-4370-ACEA-9B148D60B784-hsb-deslocamento-synthetic`
- UTC: `2026-02-18 11:36:00` -> `2026-02-18 14:04:00`
- BRT: `08:36` -> `11:04`
- Reserva starts `11:05 BRT`, so no overlap.

## Useful Commands
Dry-run (hardcoded scenario):
```bash
docker compose exec -T worker sh -lc 'python /app/hsb-ruleset-dummy.py'
```

Dry-run from real today DB data:
```bash
docker compose exec -T worker sh -lc 'python /app/hsb-ruleset-dummy.py --from-db-today'
```

Apply temporary dummy output + publish:
```bash
docker compose exec -T worker sh -lc 'python /app/hsb-ruleset-dummy.py --from-db-today --apply-db --publish-ics'
```

Remove temporary dummy rows + republish:
```bash
docker compose exec -T worker sh -lc 'python /app/hsb-ruleset-dummy.py --cleanup-only && python /app/publish_ics.py'
```

## Current Intent
Keep dummy flow temporary for rule tuning, then migrate finalized logic to production ruleset when approved.
