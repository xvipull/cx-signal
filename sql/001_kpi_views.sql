-- Reusable CXSignal KPI views. Target dialect: PostgreSQL.
-- Source fields, grain, and policy assumptions are defined in 000_source_contract.sql.

CREATE OR REPLACE VIEW cx_score_trends_monthly AS
WITH scored AS (
    SELECT date_trunc('month', i.submitted_at)::date AS month_start,
           COALESCE(i.channel, 'unknown') AS channel,
           COALESCE(i.segment, 'unknown') AS segment,
           r.question_id,
           r.question_version,
           p.question_type,
           r.response_value,
           p.satisfied_min
    FROM stg_survey_invitations i
    JOIN stg_survey_responses r USING (survey_invitation_id)
    JOIN cx_survey_question_policy p
      ON p.questionnaire_version = i.questionnaire_version
     AND p.question_id = r.question_id
     AND p.question_version = r.question_version
    WHERE i.submitted_at IS NOT NULL
      AND r.answered
      AND r.response_value BETWEEN p.scale_min AND p.scale_max
)
SELECT month_start, channel, segment, question_id, question_version, question_type,
       COUNT(*) AS valid_responses,
       CASE WHEN question_type = 'nps' THEN
           100.0 * (COUNT(*) FILTER (WHERE response_value >= 9)
                  - COUNT(*) FILTER (WHERE response_value <= 6)) / NULLIF(COUNT(*), 0)
       END AS nps,
       CASE WHEN question_type = 'csat' THEN
           100.0 * COUNT(*) FILTER (WHERE response_value >= satisfied_min) / NULLIF(COUNT(*), 0)
       END AS csat_percent
FROM scored
GROUP BY month_start, channel, segment, question_id, question_version, question_type;

-- Convenience view for consumers focused on sliced score movements.
CREATE OR REPLACE VIEW cx_segmented_score_trends AS
SELECT month_start, channel, segment, question_id, question_version, question_type,
       valid_responses, nps, csat_percent
FROM cx_score_trends_monthly;

CREATE OR REPLACE VIEW cx_complaint_rate_monthly AS
WITH complaint_counts AS (
    SELECT date_trunc('month', complaint_at)::date AS month_start,
           COALESCE(channel, 'unknown') AS channel,
           COALESCE(segment, 'unknown') AS segment,
           COUNT(DISTINCT complaint_id) AS complaints
    FROM stg_complaints
    GROUP BY 1, 2, 3
), eligible_orders AS (
    SELECT date_trunc('month', completed_at)::date AS month_start,
           COALESCE(channel, 'unknown') AS channel,
           COALESCE(segment, 'unknown') AS segment,
           COUNT(DISTINCT order_id) AS eligible_orders
    FROM stg_orders
    WHERE is_eligible_exposure
    GROUP BY 1, 2, 3
)
SELECT COALESCE(c.month_start, o.month_start) AS month_start,
       COALESCE(c.channel, o.channel) AS channel,
       COALESCE(c.segment, o.segment) AS segment,
       COALESCE(c.complaints, 0) AS complaints,
       COALESCE(o.eligible_orders, 0) AS eligible_orders,
       1000.0 * COALESCE(c.complaints, 0) / NULLIF(o.eligible_orders, 0) AS complaints_per_1000_orders
FROM complaint_counts c
FULL OUTER JOIN eligible_orders o
  ON c.month_start = o.month_start AND c.channel = o.channel AND c.segment = o.segment;

CREATE OR REPLACE VIEW cx_response_completeness_monthly AS
WITH required_answers AS (
    SELECT i.survey_invitation_id,
           date_trunc('month', i.submitted_at)::date AS month_start,
           COALESCE(i.channel, 'unknown') AS channel,
           COALESCE(i.segment, 'unknown') AS segment,
           p.question_id,
           p.question_version,
           CASE WHEN r.answered AND r.response_value BETWEEN p.scale_min AND p.scale_max THEN 1 ELSE 0 END AS answered_valid
    FROM stg_survey_invitations i
    LEFT JOIN cx_survey_question_policy p
      ON p.questionnaire_version = i.questionnaire_version AND p.is_required
    LEFT JOIN stg_survey_responses r
      ON r.survey_invitation_id = i.survey_invitation_id
     AND r.question_id = p.question_id
     AND r.question_version = p.question_version
    WHERE i.submitted_at IS NOT NULL
), per_submission AS (
    SELECT survey_invitation_id, month_start, channel, segment,
           COUNT(question_id) AS required_items,
           COALESCE(SUM(answered_valid), 0) AS valid_answers
    FROM required_answers
    GROUP BY survey_invitation_id, month_start, channel, segment
)
SELECT month_start, channel, segment,
       COUNT(*) AS submitted_invitations,
       COUNT(*) FILTER (WHERE required_items > 0 AND valid_answers = required_items) AS complete_submissions,
       100.0 * COUNT(*) FILTER (WHERE required_items > 0 AND valid_answers = required_items)
           / NULLIF(COUNT(*), 0) AS response_completeness_percent
FROM per_submission
GROUP BY month_start, channel, segment;

CREATE OR REPLACE VIEW cx_resolution_time_monthly AS
SELECT date_trunc('month', resolved_at)::date AS month_start,
       COALESCE(channel, 'unknown') AS channel,
       COALESCE(segment, 'unknown') AS segment,
       COUNT(DISTINCT resolution_id) AS resolved_episodes,
       AVG(EXTRACT(EPOCH FROM (resolved_at - case_created_at)) / 3600.0) AS avg_resolution_hours,
       percentile_cont(0.50) WITHIN GROUP
           (ORDER BY EXTRACT(EPOCH FROM (resolved_at - case_created_at)) / 3600.0) AS median_resolution_hours,
       percentile_cont(0.90) WITHIN GROUP
           (ORDER BY EXTRACT(EPOCH FROM (resolved_at - case_created_at)) / 3600.0) AS p90_resolution_hours
FROM stg_case_resolutions
WHERE is_kpi_resolution AND resolved_at >= case_created_at
GROUP BY 1, 2, 3;

CREATE OR REPLACE VIEW cx_repeat_contact_monthly AS
WITH coverage AS (
    SELECT data_through_at FROM stg_data_coverage WHERE dataset_name = 'service_interactions'
), eligible_resolutions AS (
    SELECT r.*
    FROM stg_case_resolutions r CROSS JOIN coverage c
    WHERE r.is_kpi_resolution
      AND r.customer_key IS NOT NULL
      AND r.issue_code IS NOT NULL
      AND r.resolved_at + INTERVAL '7 days' <= c.data_through_at
), follow_up AS (
    SELECT r.resolution_id, r.resolved_at, r.channel, r.segment,
           EXISTS (
               SELECT 1
               FROM stg_service_interactions s
               WHERE s.customer_key = r.customer_key
                 AND s.issue_code = r.issue_code
                 AND s.contact_at > r.resolved_at
                 AND s.contact_at <= r.resolved_at + INTERVAL '7 days'
           ) AS has_repeat_contact
    FROM eligible_resolutions r
)
SELECT date_trunc('month', resolved_at)::date AS month_start,
       COALESCE(channel, 'unknown') AS channel,
       COALESCE(segment, 'unknown') AS segment,
       COUNT(DISTINCT resolution_id) AS eligible_resolved_cases,
       COUNT(DISTINCT resolution_id) FILTER (WHERE has_repeat_contact) AS repeat_contacts,
       100.0 * COUNT(DISTINCT resolution_id) FILTER (WHERE has_repeat_contact)
           / NULLIF(COUNT(DISTINCT resolution_id), 0) AS repeat_contact_percent
FROM follow_up
GROUP BY 1, 2, 3;

CREATE OR REPLACE VIEW cx_issue_recurrence_monthly AS
WITH coverage AS (
    SELECT data_from_at FROM stg_data_coverage WHERE dataset_name = 'service_interactions'
), case_events AS (
    SELECT DISTINCT ON (case_id, customer_key, issue_code)
           case_id, customer_key, issue_code, contact_at AS case_started_at, channel, segment
    FROM stg_service_interactions
    WHERE case_id IS NOT NULL AND customer_key IS NOT NULL AND issue_code IS NOT NULL
    ORDER BY case_id, customer_key, issue_code, contact_at, interaction_id
), ordered_cases AS (
    SELECT c.*,
           LAG(case_started_at) OVER (
               PARTITION BY customer_key, issue_code ORDER BY case_started_at, case_id
           ) AS previous_same_issue_case_at
    FROM case_events c
), eligible AS (
    SELECT o.*
    FROM ordered_cases o CROSS JOIN coverage c
    WHERE o.case_started_at >= c.data_from_at + INTERVAL '30 days'
)
SELECT date_trunc('month', case_started_at)::date AS month_start,
       COALESCE(channel, 'unknown') AS channel,
       COALESCE(segment, 'unknown') AS segment,
       COUNT(DISTINCT case_id) AS eligible_issue_cases,
       COUNT(DISTINCT case_id) FILTER (WHERE previous_same_issue_case_at >= case_started_at - INTERVAL '30 days') AS recurring_issue_cases,
       100.0 * COUNT(DISTINCT case_id) FILTER (WHERE previous_same_issue_case_at >= case_started_at - INTERVAL '30 days')
           / NULLIF(COUNT(DISTINCT case_id), 0) AS issue_recurrence_percent
FROM eligible
GROUP BY 1, 2, 3;
