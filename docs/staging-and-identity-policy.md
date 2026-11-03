# Staging and identity standardization policy

**Status:** Initial implementation policy; source owners must approve mappings before production use  
**Version:** Day 5  
**Inputs:** Manifest-backed immutable raw CSV batches  
**Outputs:** Derived staging files in a separate output root

Staging verifies each raw file against its ingestion manifest before reading it. It writes standardized copies and match results to a separate derived location. It never edits, renames, or overwrites raw inputs. The checked-in examples are synthetic only.

## Standardization rules

| Field class | Rule | Invalid or unknown value behavior |
|---|---|---|
| Dates and timestamps | Trim surrounding whitespace, require ISO 8601, require an explicit timezone for timestamps, and convert timestamps to UTC with a `Z` suffix. | Missing or invalid required event/response timestamp stops the staging batch with a clear error; source raw data remains unchanged. |
| Opaque identifiers (`case_id`, `order_id`, `service_event_id`, survey IDs) | Trim surrounding whitespace; preserve case and punctuation because source IDs are opaque and may be case-sensitive. Empty values remain empty. | Do not invent IDs. Multiple records with the same join ID are handled as ambiguous candidates by the match policy. |
| Customer keys | Trim and remove internal whitespace, then case-fold. Apply only to approved pseudonymous keys, never direct identifiers. | Blank keys cannot participate in customer/time matching and are quarantined for review when no explicit key can link the survey. |
| Channel | Trim, case-fold, collapse repeated spaces, and map aliases through the versioned policy configuration (for example, `Phone` → `voice`, `web form` → `web`). | Blank becomes `unknown` with mapping status `blank`; unrecognized values remain visible as `unmapped:<normalized source value>` with status `unmapped`. Do not silently discard them. |
| Status code | Trim, case-fold, collapse repeated spaces, and map source labels through the versioned policy (for example, `Closed` → `resolved`, `In Progress` → `in_progress`). | Blank becomes `unknown`; unrecognized values remain `unmapped:<normalized source value>`. Resolve mappings with the source owner before production reporting. |

For traceability, staged channel and status fields include the normalized source label and a mapping status. Mapping changes require a new policy version and create a distinct staging batch. The sample aliases are illustrative and need source-owner review.

## Survey-to-service matching policy

The versioned policy is stored in `configs/staging/survey_service.v1.json`. It sets a proposed seven-day matching window for demonstration; Support and CX/VoC owners must approve the real window and source semantics before operational use.

1. **Verify inputs.** Require a valid ingestion manifest, exact stored-file checksum, and row count. A checksum or manifest mismatch stops staging.
2. **Normalize keys and timestamps.** Apply the rules above before matching. Customer-key normalization is valid only for approved pseudonymous keys and only after Data Governance approves linkage.
3. **Try explicit references first.** Match any shared explicit `service_event_id`, `case_id`, or `order_id`. A single unique service row is linked as `explicit:<field>`. If explicit references point to multiple service rows, quarantine the survey as `multiple_explicit_service_matches`; do not fall back to a weaker rule.
4. **Use customer plus time only when no explicit reference exists.** A candidate service event must have the same normalized customer key, occur at or before survey submission, and be within the configured window. This is a provisional association rule, not proof that the survey was about that event.
5. **Accept only a unique temporal candidate.** Exactly one eligible event is linked as `unique_customer_time_window`. More than one candidate is quarantined as `multiple_customer_time_window_matches`, including when one event is closer in time. No nearest-event tie-breaking is used.
6. **Quarantine unlinked cases.** Missing customer key yields `missing_customer_key`; no eligible candidate yields `no_eligible_service_match`. Do not treat unlinked as “no service issue.”
7. **Report coverage.** The staging manifest records matched and quarantined counts. Review quarantine reasons and linkage coverage with source owners before using linked KPIs. Keep any re-identification crosswalk outside this repository and under restricted access.

This policy prioritizes precision over match volume. It prevents ambiguous matches from silently inflating complaint, recovery, or attribution metrics. Changes to entity definition, explicit key precedence, temporal direction, or time window require a reviewed policy version.

## Run with synthetic fixtures

First ingest both checked-in fixtures to a local raw directory (the raw files are copied without modification):

```sh
PYTHONPATH=src python3 -m cx_signal.ingestion.cli \
  --input examples/fixtures/survey_responses.csv \
  --config configs/ingestion/survey_responses.v1.json \
  --raw-root /tmp/cxsignal-day5/raw

PYTHONPATH=src python3 -m cx_signal.ingestion.cli \
  --input examples/fixtures/service_events.csv \
  --config configs/ingestion/service_events.v1.json \
  --raw-root /tmp/cxsignal-day5/raw
```

Then stage using the returned batch directory paths:

```sh
PYTHONPATH=src python3 -m cx_signal.staging \
  --survey-batch /tmp/cxsignal-day5/raw/synthetic-survey/<survey-batch-id> \
  --service-batch /tmp/cxsignal-day5/raw/synthetic-service/<service-batch-id> \
  --config configs/staging/survey_service.v1.json \
  --output-root /tmp/cxsignal-day5/staged
```

The derived batch contains `staged_surveys.csv`, `staged_service_events.csv`, `survey_service_matches.csv`, `survey_match_quarantine.csv`, and a `manifest.json` with source batch IDs, input checksums, policy checksum, row/linkage counts, and output checksums. Output batches are content-addressed; an existing output is never overwritten.

## Production readiness

Before using real data, confirm pseudonymous key approval, source-specific ID case rules, channel and status mappings, timezone correctness, matching window, explicit identifier relationships, source coverage, and retention/access controls. Keep raw production data and linked staging outputs in approved restricted storage. Do not place customer records or identity crosswalks in this public repository.
