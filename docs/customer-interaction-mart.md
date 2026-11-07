# Customer and interaction analytics mart

**Model:** CXSignal dimensional mart v1  
**Builder:** `python -m cx_signal.mart`  
**Status:** Starter model; confirm source semantics and owner approvals before production use

The mart is a set of flat CSV tables with stable surrogate keys and declared grain. It is designed for reporting across customer experience, support, complaints, orders, and recovery. It contains no direct customer identifiers. Customer surrogate keys are deterministic hashes of already-approved pseudonymous input keys; they do not replace source-system identity governance.

## Dimensions

| Table | Grain | Key and attributes |
|---|---|---|
| `dim_customer` | One row per normalized pseudonymous customer key present in the input batches, plus an unknown row when needed | `customer_sk`; `identity_type` (`pseudonymous` or `unknown`). Natural customer keys are not written to the mart. |
| `dim_date` | One row per UTC calendar date represented by a fact | `date_sk` (`YYYYMMDD`); ISO date, year, quarter, month, day, ISO weekday. This is a calendar dimension, not an operational business-hours calendar. |
| `dim_issue` | One row per governed taxonomy issue code used by a fact, plus `unknown_issue` | `issue_sk` / `issue_code`; levels 1–3, canonical label, taxonomy version. Unmapped free text is not copied into the dimension. |
| `dim_channel` | One row per normalized channel value present in service interactions | `channel_sk`; normalized channel. |
| `dim_status` | One row per normalized status value present in interactions or orders | `status_sk`; normalized status. |

## Facts and grains

| Table | Grain | Foreign keys and measures/attributes |
|---|---|---|
| `fact_survey_response` | One row per survey response record/question as delivered by the source | `survey_response_sk`, `customer_sk`, `response_date_sk`; question ID/version, response value, optional survey channel. A respondent who answers multiple questions contributes one row per source response record. |
| `fact_service_interaction` | One row per service event/interaction ID | `interaction_sk`, `customer_sk`, `interaction_date_sk`, `channel_sk`, `status_sk`, `issue_sk`, issue mapping status/confidence, optional `case_sk`. One case can have multiple service events. |
| `fact_complaint` | One row per complaint record | `complaint_sk`, `customer_sk`, `complaint_date_sk`, `issue_sk`, issue mapping status/confidence, optional `case_sk`. Complaint means the source-approved complaint record/classification. |
| `fact_order` | One row per order ID | `order_sk`, `customer_sk`, `order_date_sk`, `status_sk`, optional order channel. Order-line grain and monetary measures are not included in v1. |
| `fact_resolution` | One row per resolution episode ID | `resolution_sk`, `customer_sk`, `resolution_date_sk`, `issue_sk`, issue mapping status/confidence, optional `case_sk`, resolution code. Reopened cases may have multiple resolution episodes. |

All fact tables include a `source_sha256` digest of the source record identifier for lineage without storing the source identifier itself. `*_sk` fact keys are namespaced deterministic hashes. Date and categorical foreign keys resolve to the dimensions above; absent customer, case, issue, channel, or status values use explicit unknown keys/rows where the relevant dimension exists.

## Join and aggregation rules

- Join facts to `dim_customer` by `customer_sk`, to `dim_date` by the table-specific date key, and to categorical dimensions by their surrogate keys.
- Aggregate each fact at its declared grain before combining facts. Joining survey responses directly to multiple service events or order lines can multiply rows and inflate counts.
- `case_sk` is a consistent namespaced hash across service, complaint, and resolution facts; the source case ID is not exposed. It is a degenerate linkage key, not a conformed dimension in v1.
- A common `customer_sk` does not imply that a survey response was caused by or refers to a particular interaction. Use the approved survey-service match output for interaction attribution and retain its ambiguity status.
- `dim_issue` derives from the governed taxonomy. Unmapped labels collapse to `unknown_issue`; review mapping coverage separately using the taxonomy cleaner output.
- The builder rejects blank or duplicate source IDs at each fact grain and requires timezone-aware event timestamps. Resolve source grain/schema mismatches before loading rather than silently deduplicating.

## Build from staged inputs

The survey and service inputs should be derived staging outputs from Day 5. Complaint, order, and resolution files must also be cleaned and schema-approved before use.

```sh
PYTHONPATH=src python3 -m cx_signal.mart \
  --surveys /path/to/staged_surveys.csv \
  --service-interactions /path/to/staged_service_events.csv \
  --complaints examples/fixtures/complaints.csv \
  --orders examples/fixtures/orders.csv \
  --resolutions examples/fixtures/resolutions.csv \
  --taxonomy configs/taxonomy/issue_taxonomy.v1.json \
  --output-dir /path/to/cxsignal-mart
```

The output includes the five fact tables, five dimensions, and `mart_manifest.json` with row counts, source-file checksums, taxonomy version, and output checksums. Keep production mart outputs in approved controlled storage. The checked-in example is generated only from synthetic fixtures.
