# CXSignal data-quality controls

**Policy:** `configs/quality/data_quality.v1.json`  
**Status:** Initial checks; owners must approve thresholds and required-field rules for production sources

The quality command reads only manifest-backed raw batches. It verifies each input checksum and row count before running checks. It writes a JSON summary, a readable Markdown report, and a CSV issue ledger. Issue references are one-way hashes of record identifiers; actual customer or interaction IDs and source field values are omitted from issue details.

## Checks

- **Required fields:** checks configured required columns for blank values in survey and service rows.
- **Duplicate interactions:** checks configured stable interaction keys, currently `service_event_id`. It does not assume `case_id` is unique because one case may have multiple service events.
- **Invalid scores:** validates configured score ranges by question (NPS 0–10 and sample CSAT 1–5). Unknown question IDs without a configured range are warnings.
- **Impossible timestamps:** detects malformed or timezone-free timestamps, timestamps beyond the configured future tolerance, event end before event start, and resolution before case creation when both fields are available.
- **Orphaned customers:** warns when a nonblank survey customer key has no corresponding service customer key in the input batches. This is a batch-level linkage diagnostic, not proof that a customer had no service interaction.
- **Stale inputs:** compares each manifest's source extraction timestamp to the configured maximum age. Missing or invalid extraction times are warnings; future extraction times are failures.
- **Response completeness:** checks configured required answer fields and reports complete/incomplete counts and percentage. Invitations and response rates use separate denominators and are outside this check.

Failures indicate data conditions that make the checked rows unsafe for the configured use; warnings indicate coverage or freshness limitations. Overall status is `fail` if any failure exists, otherwise `warn` if any warning exists, otherwise `pass`. Exit code is 1 only for a failing report, 0 for warning/pass, and 2 when the quality run itself cannot be completed.

## Run

```sh
PYTHONPATH=src python3 -m cx_signal.ingestion.cli \
  --input examples/fixtures/survey_responses.csv \
  --config configs/ingestion/survey_responses.v1.json \
  --raw-root /tmp/cxsignal-day7/raw

PYTHONPATH=src python3 -m cx_signal.ingestion.cli \
  --input examples/fixtures/service_events.csv \
  --config configs/ingestion/service_events.v1.json \
  --raw-root /tmp/cxsignal-day7/raw

PYTHONPATH=src python3 -m cx_signal.quality \
  --survey-batch /tmp/cxsignal-day7/raw/synthetic-survey/<survey-batch-id> \
  --service-batch /tmp/cxsignal-day7/raw/synthetic-service/<service-batch-id> \
  --config configs/quality/data_quality.v1.json \
  --output-dir reports/data-quality-run
```

The output directory contains `quality_report.json`, `quality_report.md`, and `quality_issues.csv`. Reports use extraction timestamps from the immutable raw manifests, not file modification times. Tune required fields, score scales, duplicate keys, timestamp semantics, freshness thresholds, and completeness fields only with the accountable data owners.

## Example report

`reports/data-quality-example/` contains a generated report for the checked-in synthetic survey and service fixtures. Its stale-input warning is expected because the fixture extraction date is intentionally historical relative to report generation. The report is illustrative and must not be used as a production quality assessment.
