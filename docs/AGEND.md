# Agenda

## Completed

- Added dedupe protection in `init_parsing.py` to avoid duplicate non-synthetic rows across cycles:
  - same-cycle dedupe: `duplicate_event_content`
  - cross-cycle dedupe: `duplicate_event_existing`
- Removed duplicated `Apresentação` rows and dependent synthetic children from `processed_events` for `roque`.
- Re-ran synthesis and publish stages to regenerate `Checkout`, `Horário Corte`, and `Final de Jornada` from clean source rows.
- Updated worker guide to reflect current loop stages and dedupe behavior.

## Ongoing Monitoring

- Confirm no recurrence of duplicate synthetic chains after new ingest cycles.
- Spot-check `Checkout` placement against `Apresentação` source times for upcoming March duties.
- Keep validating that source-injected synthetic-like titles are filtered during parsing.

## Next If Needed

- Add an audit query/report job that flags potential duplicate duty chains per day before publish.
- Add a publish-time guard to reject duplicate `(summary, dtstart, dtend)` triplets.
