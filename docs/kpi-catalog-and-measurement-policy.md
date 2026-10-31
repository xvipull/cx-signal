# CX KPI catalog and measurement policy

**Status:** Working definitions for stakeholder approval  
**Version:** Day 2  
**Applies to:** CXSignal descriptive reporting and baseline analysis  
**Decision owner:** CX Head; metric stewards are listed below

These definitions are intended to make reporting reproducible. They are not approved production targets. Before publishing a baseline, confirm question wording, source semantics, channel coverage, reporting population, and operational windows with the named data owners. If a source cannot support a definition, report the gap instead of silently changing its meaning.

## KPI catalog

| KPI | Definition and calculation | Denominator and inclusion rules | Owner / steward |
|---|---|---|---|
| **NPS** | For a standard 0–10 likelihood-to-recommend question: `% Promoters (9–10) − % Detractors (0–6)`. Passives (7–8) count in the valid-response denominator but not either numerator. Report as points on a −100 to +100 scale. | Valid, in-scope responses to the exact NPS question in the reporting period. Exclude blank, invalid, test, and duplicate submissions under the deduplication policy. Do not divide by invitations, delivered surveys, or all customers. | CX / VoC owner; CX Head approves interpretation |
| **CSAT** | `% satisfied = qualifying satisfied responses ÷ valid responses to the specified satisfaction item × 100`. The qualifying top-box or top-two-box values depend on the survey scale and must be declared with every chart (for example, 4–5 on a 5-point scale). | Valid answers to the named CSAT item, using the same question wording and scale. Exclude blank/invalid answers and duplicate submissions. Do not combine scales or question variants without an approved harmonization method. | CX / VoC owner; Support or Product steward for transactional CSAT |
| **Complaint rate** | `distinct in-scope complaint cases ÷ eligible exposure opportunities × 1,000` (or another explicitly labeled multiplier). A complaint is a contact classified as a complaint using the approved case taxonomy, not every support contact. | Choose and label one denominator appropriate to the decision: eligible completed transactions/orders for transaction complaints; or active customers for a customer-period complaint rate. Count only exposure in the same population, period, and segment as the numerator. Report denominator volume and taxonomy coverage. | Support Operations owns case classification; Operations/Data owner owns exposure denominator; CX Head approves the reporting view |
| **Resolution time** | Elapsed time from case creation to first valid resolved timestamp. Report median and a stated percentile (for example, p90); optionally show mean only with distribution context. Specify calendar or business hours, time zone, paused-time handling, and whether reopening resets the clock. | Resolved, eligible cases created in the cohort period, with valid start and resolution timestamps. Open cases are not treated as resolved or discarded silently; report open backlog and age separately. For cohort reporting, include cases created in the period and resolve them after a fixed maturation window, or label the metric as provisional. | Support Operations owns lifecycle semantics and service calendar; Analytics steward implements calculation |
| **Repeat contact** | `% repeat-contact cases = eligible resolved cases with a subsequent same-customer, same-issue contact within W days ÷ eligible resolved cases with a full W-day observation window × 100`. W is a configurable, published window; use 7 calendar days only as a proposed starting point pending Support approval. | Use eligible index cases resolved in the cohort period, require approved identity linkage and issue matching, exclude contacts outside the defined channels/population, and only include cases whose entire follow-up window is observable. Report linkage and taxonomy coverage. | Support Operations owns issue taxonomy and case lifecycle; Data Governance approves identity linkage; Analytics steward calculates |
| **Detractor recovery** | `recovered detractors ÷ eligible detractor cases × 100`. A recovered detractor is a customer who both had an actionable detractor-triggering experience and meets a predeclared recovery outcome after an approved intervention. Recommended outcome: a subsequent valid, linked score moves above 6 on the same 0–10 NPS question within a declared follow-up window. | Eligible detractor-triggering cases with an attempted, documented recovery intervention and sufficient follow-up opportunity. Report separately: intervention coverage, follow-up response rate, and score-change distribution. Nonresponse is unknown, not recovery or failure; do not impute a new score. | CX Head owns outcome definition; Support owns intervention logging; CX/VoC owns survey; Analytics steward reports linkage and response coverage |
| **Issue recurrence** | `recurring issue cases ÷ eligible issue cases × 100`, where a recurring case is a new case matching a previously observed issue for the same approved entity (customer, account, asset, or service) within recurrence window W. Define the entity and matching level explicitly. | Eligible cases with a valid issue classification and sufficient prior history over W. Exclude duplicate/merged case records according to the case policy. If linkage or classification is unavailable, report recurrence as unavailable or provide a clearly labeled aggregate issue-volume trend instead. | Support Operations owns case taxonomy; Product or Operations owns issue remediation domain; Analytics steward calculates |
| **Response completeness** | `% complete responses = submissions satisfying the declared completeness rule ÷ valid survey submissions × 100`. Default rule: all required core experience items are answered. Optional items and branching questions are not required. State whether partials with a valid NPS/CSAT answer remain eligible for those item-level KPIs. | Survey submissions that reached the defined submission state and passed validity and deduplication checks. The denominator is submissions, not invitations or delivery events. Report item-level missingness and response completeness separately; survey response rate uses a separate invitations denominator. | CX / VoC owner owns questionnaire and required-item rules; Analytics steward applies them |

## Measurement policy

### Population, period, and reporting

- Every reported KPI must state its population, channel/product scope, geography if relevant, event/cohort date, reporting period, refresh date, and denominator count.
- Use event date appropriate to the metric: response timestamp for survey KPIs, case creation date for complaint and recurrence cohorts, and case resolution date or creation cohort for resolution-time views. Name the choice in the chart or query.
- Keep numerator and denominator aligned on population, time basis, segment, and inclusion rules. Do not compare rates with different denominator definitions as if they were equivalent.
- Use distinct, stable event or case identifiers to deduplicate. Document the rule for merged, reopened, transferred, or corrected records.
- Preserve the source value and lineage for derived metrics. Record query/code version and transformations so a result can be reproduced.
- Suppress or combine small groups under organizational privacy policy before sharing. Never commit customer-level data or direct identifiers to this repository.
- Show counts and missingness alongside percentages. Mark low-volume estimates as unstable using an approved threshold or uncertainty interval.
- Do not compare across question wording, scale, channel mix, taxonomy version, or service-calendar changes without flagging the break or validating comparability.

### Survey linkage assumptions

Survey-to-case linkage is permitted only when the source owner and Privacy/Data Governance approve the purpose, fields, and retention. Proposed linkage assumptions, to validate before analysis:

1. Link using an approved pseudonymous customer/account key held in a restricted environment; do not use email, phone, name, or free text in the analytical repository.
2. Require a valid event timestamp and a documented relationship between survey invitation/response and the service interaction (for example, an explicit transaction or case reference, or an approved time-window rule).
3. Prefer explicit interaction references. If a time-window join is used, define the window, tie-breaking rule, and behavior when multiple cases are eligible; do not assign a response to the nearest case by default without validation.
4. Enforce one response-to-interaction mapping unless the survey design explicitly supports multiple interactions. Deduplicate repeat submissions under a documented rule, such as retaining the latest valid response per invitation or interaction.
5. Keep unlinked responses in survey-level NPS/CSAT reporting when otherwise valid, but exclude them from case-level recovery attribution. Report eligible, linked, ambiguous, and unlinked counts and rates.
6. Validate join precision and coverage on an approved sample before using linked metrics. Treat missing linkage as unknown, not as absence of a service issue.

### Attribution assumptions and limits

- Descriptive association between an experience score, contact, intervention, or issue and a later outcome does not establish that one caused the other.
- Attribute a survey response to an intervention only when timing, approved identity linkage, and intervention logging support the relationship. Define the response window and require the intervention to precede the outcome.
- Detractor recovery is subject to follow-up response bias: customers who respond may differ from nonresponders. Publish response rate and linkage coverage beside the recovery rate; do not generalize the observed rate to all detractors without a defensible design.
- A before/after score change can reflect other events, regression to the mean, or survey/channel differences. Use randomized or otherwise appropriate comparison designs for causal claims and have the design reviewed by the analytics owner.
- Issue recurrence is a measured match under a taxonomy and time window, not proof that the same root cause persisted. Root-cause claims require domain review.
- Report attribution as “associated with” unless an approved evaluation supports causal language.

## Proposed defaults requiring owner approval

| Policy item | Proposed default | Approver |
|---|---|---|
| Repeat-contact follow-up window | 7 calendar days after index-case resolution | Support Operations |
| Detractor recovery outcome | Subsequent same-question 0–10 NPS score above 6 | CX Head and CX/VoC |
| Detractor recovery follow-up window | Set from survey cycle and interaction type; no universal value assumed | CX/VoC and Support |
| Issue recurrence window | Define by issue domain; no universal value assumed | Support Operations plus Product/Operations domain owner |
| Survey duplicate handling | One latest valid response per invitation or interaction, pending survey design | CX/VoC |
| Complaint exposure denominator | Transaction/order volume for transaction complaint rate; active customers for customer-period rate | CX Head and relevant source owner |

## Readiness checklist before KPI publication

- Metric owner approves the business definition and any proposed defaults.
- Source owner approves access, purpose, and field-level use; privacy review is complete where required.
- Denominator coverage, data quality, linkage coverage, exclusions, and observation windows are documented.
- Counts, missingness, freshness, and relevant survey or taxonomy changes are visible with the results.
- The report states whether findings are descriptive, associational, or causally evaluated.
- A named decision owner and action path exist for any operational use of the result.
