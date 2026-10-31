# CX data sources and dictionary

**Status:** Candidate source map; systems, fields, and owners require confirmation  
**Version:** Day 3  
**Decision owner:** CX Head  
**Data governance:** Source owners and Data Governance approve access, joins, retention, and permitted use before ingestion.

This document describes the minimum source domains needed for CXSignal and a logical data dictionary. It does not assert that any particular system is connected or approved. Replace candidate names and keys with source-specific details during discovery. Do not infer semantics from a column name alone.

## Source map

| Source domain | Candidate system / authoritative owner | Expected source grain | Candidate primary key | Candidate join keys | Key questions before use |
|---|---|---|---|---|---|
| Survey | VoC / survey platform; CX or VoC owner | One answer per respondent, question, and survey submission; some systems store one row per submission with question fields | `survey_response_id`; possibly `submission_id` plus `question_id` | Approved pseudonymous `customer_key`; `survey_invitation_id`; optional `interaction_id`, `case_id`, `order_id`; response timestamp | Question wording and scale versions? Invitation vs submission semantics? Duplicate/partial response behavior? Consent/notice and retention? |
| Complaint | CRM / complaints register; Support Operations or complaints owner | One complaint record or complaint classification per case; confirm whether several complaints can attach to one case | `complaint_id` or `case_id` plus complaint sequence | `case_id`, approved `customer_key`, `service_event_id`, `order_id`, complaint-created timestamp | What qualifies as a complaint? Are classifications audited? How are reopened, transferred, and duplicate complaints handled? |
| Ticket / support case | Contact center, CRM, or case management; Support Operations | One case/ticket lifecycle record; event history may be one row per status event or contact | `case_id`; status event ID for event history | Approved `customer_key`; `interaction_id`; `order_id`; `service_event_id`; created/resolved timestamps | Case vs contact distinction? Merge and reopen rules? Channel coverage? Business calendar and pause states? |
| Service event | Service, delivery, incident, or operations platform; relevant Operations owner | One service occurrence, incident, outage, or fulfillment event; event subrecords may be one row per affected entity | `service_event_id` or incident ID | `order_id`, approved `customer_key`/account key, affected product/service key, case ID, event timestamps | What is an event vs a status update? Scope of affected customers? Start/end semantics? Incident severity and taxonomy ownership? |
| Order | Order management / commerce system; Order Operations or Commerce owner | One order; line-level table has one row per order line | `order_id`; line-level `order_line_id` | Approved `customer_key`, product/service key, `service_event_id`, case ID, order and delivery timestamps | Which order states count as completed/exposed? Cancellation, return, partial fulfillment, and currency rules? |
| Resolution | Case lifecycle history / resolution outcome source; Support Operations | One resolution outcome per case-resolution episode; may be multiple episodes for reopened cases | `resolution_id` or `case_id` plus resolution sequence | `case_id`, `customer_key` through approved linkage, issue code, resolution timestamp, intervention ID | What counts as resolved? Is customer confirmation required? How are reopened cases and multi-step resolutions represented? |
| Customer | Customer master / identity service; Data Governance and customer-data owner | One customer/account record per entity and validity period; slowly changing dimensions may have multiple versions | Source customer ID; CXSignal uses a restricted pseudonymous `customer_key` | Controlled identity crosswalk; approved account/household relationship; validity dates | Entity definition (person/account/household)? Merge/split behavior? Effective dating? Access, retention, and re-identification controls? |
| Calendar | Approved organizational calendar and timezone reference; Operations / Analytics | One row per date per calendar and region, or one row per working interval | `calendar_date` plus `calendar_id` | Case created/resolved dates; event dates; region/timezone/calendar ID | Holidays, weekends, working hours, daylight-saving changes, regional calendars, and version history? |

## Logical data dictionary

Names below are logical names, not a commitment to source field names. Types and nullability must be mapped and validated for each source. Direct identifiers and raw free text are intentionally excluded from the analytical dictionary.

| Logical field | Meaning | Expected type / example | Grain / null rule | Source domains | Handling and notes |
|---|---|---|---|---|---|
| `survey_response_id` | Stable identifier for one survey submission or response record | String | Survey submission; required where source provides it | Survey | Pseudonymize if it embeds identity; deduplicate using documented invitation/submission rules |
| `survey_invitation_id` | Identifier for a survey invitation | String | Invitation; optional in response data | Survey | Use for invitation-to-response rates and controlled response deduplication |
| `question_id` | Survey question identifier | String | One answer/question; required for item-level records | Survey | Preserve question wording/scale version in metadata |
| `question_version` | Version of item text, scale, and presentation | String | Required for comparability assessment | Survey | Do not combine versions without documented comparability decision |
| `response_value` | Coded answer to a survey item | String or numeric | One answer per question; nullable for skipped items | Survey | Store scale metadata; normalize only in a derived field with lineage |
| `response_submitted_at` | Time response was submitted | Timestamp with timezone | Submission; required for period assignment | Survey | Preserve source timezone and normalized UTC timestamp |
| `case_id` | Stable support case/ticket identifier | String | Case; required for case-level metrics | Complaint, Ticket, Resolution | Source key; retain under approved access; never expose customer identity through derived IDs |
| `case_created_at` | Case creation time | Timestamp with timezone | Case; required for elapsed duration | Ticket | Distinguish case creation from first agent response/contact |
| `case_status` | Status at a recorded point in the lifecycle | Categorical string | Status snapshot/event; optional in current-state extracts | Ticket | Capture status taxonomy and whether record is current state or history |
| `case_resolved_at` | Timestamp for a valid resolution episode | Timestamp with timezone | Resolution episode; nullable while open | Resolution, Ticket | Do not fill from closure/last-updated time unless approved semantic mapping supports it |
| `resolution_code` | Coded outcome or disposition | Categorical string | Resolution episode; may be unknown | Resolution | Preserve source code and versioned mapping; unknown is not “other” unless explicitly mapped |
| `complaint_id` | Stable complaint record identifier | String | Complaint; required when complaints are separately recorded | Complaint | May differ from `case_id`; document one-to-many relationship |
| `complaint_flag` | Whether an approved complaint rule classifies the record as a complaint | Boolean / categorical | Case or complaint record; nullable until classification available | Complaint, Ticket | Derived only from approved taxonomy; retain rule and taxonomy version |
| `issue_code` | Standardized issue category | Categorical string | Case, complaint, or event; may be unknown | Complaint, Ticket, Service event, Resolution | Store taxonomy version and mapping; do not equate issue category with verified root cause |
| `service_event_id` | Stable identifier for an incident or service occurrence | String | Service event; required when available | Service event, Ticket, Order | Document affected-entity cardinality and event window |
| `event_started_at` / `event_ended_at` | Start/end of service impact under source semantics | Timestamp with timezone | Service event; end may be null for ongoing events | Service event | Validate planned vs actual times and inclusive/exclusive boundaries |
| `order_id` | Stable order/transaction identifier | String | Order; required for order-level metrics | Order, Ticket, Service event, Survey if explicit reference | Source key; never substitute fuzzy customer-time matching without approval |
| `order_line_id` | Stable line identifier within an order | String | Order line; required for line-grain metrics | Order | Do not mix order and order-line counts in one denominator |
| `order_status` | Lifecycle status of an order | Categorical string | Order or order line; nullable only if unavailable | Order | Map statuses with Order Operations approval; state which statuses are eligible exposure |
| `order_completed_at` | Completion/fulfillment timestamp | Timestamp with timezone | Order or line depending on source | Order | Define completion per business process; avoid assuming creation implies exposure |
| `customer_key` | Approved pseudonymous entity key for analysis | String/token | Entity and validity period; nullable for unlinked records | Customer and approved linked sources | Derived via restricted crosswalk; no direct identifiers in this repository |
| `customer_valid_from` / `customer_valid_to` | Effective period for customer/account attributes or linkage | Date/timestamp | Customer version; end nullable for current version | Customer | Use temporal joins to avoid linking against future or stale entity states |
| `calendar_id` | Organizational working calendar and timezone identifier | String | Calendar definition; required for business-hours calculations | Calendar, Ticket | Include region and version where relevant |
| `calendar_date` | Local calendar date in the applicable region | Date | One row per date/calendar; required | Calendar | Preserve region and timezone semantics for holiday/weekend logic |
| `source_system` | Originating system identifier | String | Every ingested record; required | All | Controlled vocabulary; do not use a free-form personal or environment name |
| `source_record_id` | Original source record key | String | Every ingested record; required where available | All | Keep only in approved restricted storage if identifying; can be tokenized for analysis |
| `source_extracted_at` | Time the source extract was produced | Timestamp with timezone | Extract/batch or record; required for batch metadata | All | Distinguish extraction time from source event/updated time |
| `source_updated_at` | Last source-system update time | Timestamp with timezone | Record; nullable if source does not expose it | All | Preserve for change-data interpretation; not interchangeable with event time |
| `ingestion_batch_id` | Identifier for one immutable ingestion batch | String | Batch; required | All | Links rows to provenance manifest and replay/reconciliation record |

## Grain and join policy

- Declare the grain of every source table and derived dataset in its schema or metadata. Example: one row per case-resolution episode is not one row per case.
- Before joining, test key uniqueness at the declared grain, null rates, orphan rates, and relationship cardinality. Document expected one-to-one, one-to-many, or many-to-many relationships.
- Aggregate child records to the intended analytical grain before joining when a raw join would multiply counts or exposure denominators.
- Prefer explicit source references (`case_id`, `order_id`, `interaction_id`, `survey_invitation_id`) over temporal or fuzzy matching.
- Use `customer_key` only through an approved identity service or controlled pseudonymous crosswalk. Apply effective-date constraints to customer dimension joins.
- Do not join surveys to cases solely because customer and timestamps appear close unless the matching rule has owner approval, validation, ambiguity handling, and measured precision/coverage.
- A missing key means “unlinked/unknown,” not “no associated event.” Report join coverage and unmatched records.
- Record key transformations, normalization, timezone conversion, code mapping, deduplication, and row-count changes. Reconcile input/output counts where possible.

## Raw data preservation and provenance

1. Keep source extracts immutable in an approved, access-controlled storage location outside this public Git repository. The `data/raw/` directory is for documentation and synthetic examples only; do not add real or pseudonymized customer records to Git.
2. Store each approved extract as a dated/versioned batch without overwriting prior raw batches. Restrict access and retention according to the source owner's policy and approved project purpose.
3. Maintain a provenance manifest per batch containing: `ingestion_batch_id`, source owner/system, extraction timestamp, event-time range, schema/version, extraction query or job version, file/object checksum, row count, access approval reference, sensitivity classification, retention/deletion date, and any redaction or tokenization step. Do not put credentials or direct identifiers in the manifest.
4. Preserve source field values in the controlled raw layer. Apply cleaning, normalization, filtering, and joins only in derived layers, with transformation code/version and input batch IDs recorded.
5. When a source correction requires replacement, retain the prior batch under retention controls, record the correction reason and superseding batch, and make the active version explicit. If policy requires deletion, record an approved deletion event without retaining the prohibited data.
6. Do not publish proprietary schemas, customer-level samples, connection strings, access tokens, or sensitive free-text examples in this public repository. Commit only logical definitions, approved metadata, code, and synthetic fixtures.

### Provenance manifest template

Use this template in the approved controlled data catalog or storage location. Do not populate it with secrets or personal data in Git.

| Field | Value |
|---|---|
| Ingestion batch ID | `<unique-batch-id>` |
| Source domain / system | `<domain-and-approved-system-name>` |
| Accountable source owner | `<role-or-approved-owner-reference>` |
| Approval / purpose reference | `<governance-ticket-or-approval-id>` |
| Extracted at (timezone) | `<timestamp>` |
| Event-time range | `<start> to <end>` |
| Schema / taxonomy version | `<version>` |
| Extraction job / query version | `<version-or-controlled-reference>` |
| Object checksum | `<checksum>` |
| Row count | `<count>` |
| Sensitivity classification | `<approved-classification>` |
| Tokenization / redaction | `<method-and-version-or-none>` |
| Retention / deletion date | `<date-or-policy-reference>` |
| Supersedes / correction note | `<batch-id-and-reason-or-none>` |

## Discovery and approval checklist

- Confirm authoritative system, business owner, technical custodian, and data steward for each source domain.
- Obtain data dictionary, sample schema, taxonomy/version history, and lifecycle semantics through approved channels.
- Confirm source grain and primary key uniqueness; profile nulls, duplicates, update history, and timezones.
- Agree eligibility states and denominator exposure with the metric owners in the KPI policy.
- Validate key cardinality and join precision/coverage in an approved environment before linked reporting.
- Complete privacy, security, retention, and access review before any data extraction or linkage.
- Record actual system/field mapping and decisions in version control without exposing sensitive examples.
