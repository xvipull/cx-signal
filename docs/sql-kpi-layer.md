# CXSignal SQL KPI layer

**SQL dialect:** PostgreSQL 14+  
**Contracts:** `sql/000_source_contract.sql`  
**Views:** `sql/001_kpi_views.sql`

The SQL layer creates reusable monthly views for NPS/CSAT trends, complaint rate, response completeness, resolution time, repeat contacts, issue recurrence, and segmented trends. Each KPI view groups by month, channel, and segment where the source supports those fields. `cx_segmented_score_trends` is a convenience view for sliced NPS/CSAT analysis; the operational KPI views also retain channel and segment columns.

## Source tables

Run `000_source_contract.sql` to create the standardized input and metric-policy tables. Load approved data at the documented grain, then run `001_kpi_views.sql`. The contracts require survey invitations as well as answer records so the completeness denominator includes submitted invitations even when required answers are missing. They also require case lifecycle timestamps and event coverage boundaries, which are absent from the initial Day 8 mart's date-only fact columns.

Use pseudonymous customer keys in `stg_service_interactions` and `stg_case_resolutions`; do not load direct identifiers. Populate `cx_survey_question_policy` with the approved questionnaire version, question scale, satisfied threshold, and required-item flag. Populate `stg_data_coverage` with verified event-time bounds before using repeat-contact or issue-recurrence views.

## KPI view definitions

| View | Calculation | Denominator and policy |
|---|---|---|
| `cx_score_trends_monthly` | NPS = 100 × (promoters − detractors) / valid NPS answers; CSAT = 100 × satisfied answers / valid CSAT answers. Promoters score 9–10; detractors 0–6; passives 7–8. | Valid answers are within the question's configured scale and attached to a submitted invitation. CSAT uses `satisfied_min`. Output is per question version, month, channel, and segment. |
| `cx_segmented_score_trends` | Same score measures, with channel and segment available for trend comparisons. | Same denominator and validity rules as `cx_score_trends_monthly`; do not compare question versions without a documented comparability decision. |
| `cx_complaint_rate_monthly` | Distinct approved complaint records ÷ distinct eligible completed orders × 1,000. | Eligible order exposure is explicitly controlled by `stg_orders.is_eligible_exposure`; complaints and orders are grouped by their event month, channel, and segment. A zero denominator returns NULL. Confirm that the complaint and exposure periods are the desired business comparison. |
| `cx_response_completeness_monthly` | Submitted invitations with every required question answered within its approved scale ÷ submitted invitations × 100. | All submitted invitations are included. Required questions come from `cx_survey_question_policy`; an invitation with no configured required questions is counted as incomplete and should be caught during configuration review. |
| `cx_resolution_time_monthly` | Calendar hours from case creation to resolution; returns mean, median, and p90. | Resolution episodes with `resolved_at >= case_created_at`, grouped by resolution month, channel, and segment. This uses elapsed calendar hours; business-hours calendars require a separately approved calculation. |
| `cx_repeat_contact_monthly` | Eligible resolved cases followed by another interaction for the same customer and issue within 7 calendar days ÷ eligible resolved cases × 100. | Uses rows marked `is_kpi_resolution` and excludes right-censored resolutions without a complete seven-day follow-up window using `stg_data_coverage.data_through_at`. The source owner must identify the qualifying resolution episode per case. |
| `cx_issue_recurrence_monthly` | Cases preceded by the same customer's same issue in the prior 30 days ÷ eligible issue cases × 100. | The earliest interaction per case and issue supplies the case start date and segment. Denominator excludes left-censored cases without 30 days of source history using `stg_data_coverage.data_from_at`. The metric indicates recurrence under the issue code, not proven root cause. |

All views return `month_start`, `channel`, and `segment` where relevant. Missing segment/channel labels are grouped as `unknown`. Rates are NULL when the denominator is zero rather than presenting a false zero. The 7-day repeat-contact and 30-day recurrence windows are proposed starting definitions and should be reconciled with the approved KPI policy before operational reporting.

## Run order

1. Create the contract tables from `sql/000_source_contract.sql`.
2. Load and validate source data and survey question policy at the declared grain.
3. Populate complete data coverage for service interactions.
4. Create the views from `sql/001_kpi_views.sql`.
5. Query the views for monthly totals or filter/group by channel and segment for trend reporting.

The SQL files were authored for PostgreSQL and have not been run against a connected database in this project workspace. Production adoption requires mapping approved source systems into the contract tables and validating the outputs with KPI owners.
