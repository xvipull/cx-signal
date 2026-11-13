# Survey-service reconciliation controls

**Policy:** `configs/reconciliation/survey_service.v1.json`  
**Output:** hashed record-level `linkage_audit.csv`, JSON summary, and Markdown report  
**Status:** Initial tolerances for stakeholder review; tune with CX/VoC, Support, and Data Governance

The Day 5 matching process proposes links using explicit identifiers first and a unique customer/time-window candidate only when explicit references are absent. Day 9 reconciliation accounts for every survey response and service event as matched, unmatched, or ambiguous, records the reason, and checks coverage against explicit tolerances.

## Audit dispositions

- A **matched survey** has one accepted link in `survey_service_matches.csv`.
- An **ambiguous survey** has multiple explicit or temporal service candidates. Its audit row lists all candidate service references; the matcher does not select the nearest candidate.
- An **unmatched survey** has no confirmed link and no ambiguous candidate set. The reason comes from the quarantine table, such as `no_eligible_service_match` or `missing_customer_key`.
- A **matched service event** has one or more accepted survey links and is not also a candidate in an ambiguous survey.
- An **ambiguous service event** appears as a candidate for an ambiguous survey. If an event also has a confirmed link to another survey, its audit row keeps both confirmed and ambiguous survey references and uses the ambiguous disposition for conservative rate reporting.
- An **unmatched service event** has neither a confirmed link nor membership in any ambiguous candidate set.

The audit stores one row per survey and one row per service event, with disposition, confirmed links, matching method(s), ambiguous candidates, and reason. Record identifiers are one-way hashed; confirmed and candidate relationships use the same namespaced hashed references. These references support reconciliation without putting source IDs in the report.

## Rates and default tolerance thresholds

Each rate denominator is the total number of records on that side of the audit, after the configured source population and matching window have been applied:

| Threshold | Default | Meaning |
|---|---:|---|
| Minimum survey match rate | 60% | Matched survey responses / all survey responses |
| Maximum unmatched survey rate | 25% | Unmatched survey responses / all survey responses |
| Maximum ambiguous survey rate | 35% | Ambiguous survey responses / all survey responses |
| Minimum service match rate | 50% | Matched service events / all service events |
| Maximum unmatched service rate | 25% | Unmatched service events / all service events |
| Maximum ambiguous service rate | 55% | Ambiguous service events / all service events |

Threshold boundaries are inclusive: a rate exactly at a minimum or maximum passes. Overall status fails if any threshold fails. Empty input populations produce zero rates, so minimum match-rate thresholds fail for an empty side; no division-by-zero or implicit pass occurs. These values are starting controls, not business targets. Owners should approve thresholds after reviewing historical coverage, survey sampling, and expected service-event capture.

## Run reconciliation

```sh
PYTHONPATH=src python3 -m cx_signal.reconciliation \
  --staging-dir /path/to/day5-staging-batch \
  --policy configs/reconciliation/survey_service.v1.json \
  --output-dir /path/to/new-reconciliation-output
```

The staging directory must contain the manifest, staged survey/service files, match table, and quarantine table. The process creates or refreshes `linkage_audit.csv`, `reconciliation_summary.json`, and `reconciliation_report.md` in the output directory. Exit code is 0 when every threshold passes, 1 when reconciliation runs but a threshold fails, and 2 if the audit cannot be built.

Use the portable SQL examples in [reconciliation-queries.sql](reconciliation-queries.sql) to inspect record counts, unmatched populations, and ambiguous candidate sets after loading `linkage_audit.csv` into a query engine. Avoid interpreting a successful threshold check as proof that a temporal survey-service association is causal.

## Review controls

- Review the match window, explicit identifier semantics, customer-key linkage approval, candidate cardinality, and threshold values with source owners.
- Investigate ambiguous cases without automatically picking the closest event.
- Track unmatched and ambiguous reason distributions over time; changes may reflect source coverage or taxonomy changes rather than customer experience.
- Keep audit outputs in approved controlled storage for real data. The checked-in report uses synthetic fixtures only.
