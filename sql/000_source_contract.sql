-- CXSignal KPI input contract. Target dialect: PostgreSQL.
-- Load approved, standardized data into these tables before applying 001_kpi_views.sql.
-- Customer keys must be approved pseudonymous keys; do not load direct identifiers here.

CREATE TABLE IF NOT EXISTS stg_survey_invitations (
    survey_invitation_id text NOT NULL PRIMARY KEY,
    questionnaire_version text NOT NULL,
    invited_at timestamptz,
    submitted_at timestamptz,
    channel text,
    segment text
);

CREATE TABLE IF NOT EXISTS stg_survey_responses (
    survey_invitation_id text NOT NULL,
    question_id text NOT NULL,
    question_version text NOT NULL,
    response_value numeric,
    answered boolean NOT NULL DEFAULT false,
    PRIMARY KEY (survey_invitation_id, question_id, question_version)
);

CREATE TABLE IF NOT EXISTS cx_survey_question_policy (
    questionnaire_version text NOT NULL,
    question_id text NOT NULL,
    question_version text NOT NULL,
    question_type text NOT NULL CHECK (question_type IN ('nps', 'csat', 'other')),
    scale_min numeric,
    scale_max numeric,
    satisfied_min numeric,
    is_required boolean NOT NULL DEFAULT false,
    PRIMARY KEY (questionnaire_version, question_id, question_version)
);

CREATE TABLE IF NOT EXISTS stg_service_interactions (
    interaction_id text NOT NULL PRIMARY KEY,
    case_id text,
    customer_key text,
    contact_at timestamptz NOT NULL,
    channel text,
    segment text,
    issue_code text
);

CREATE TABLE IF NOT EXISTS stg_complaints (
    complaint_id text NOT NULL PRIMARY KEY,
    complaint_at timestamptz NOT NULL,
    order_id text,
    channel text,
    segment text
);

CREATE TABLE IF NOT EXISTS stg_orders (
    order_id text NOT NULL PRIMARY KEY,
    completed_at timestamptz NOT NULL,
    is_eligible_exposure boolean NOT NULL,
    channel text,
    segment text
);

CREATE TABLE IF NOT EXISTS stg_case_resolutions (
    resolution_id text NOT NULL PRIMARY KEY,
    case_id text NOT NULL,
    customer_key text,
    case_created_at timestamptz NOT NULL,
    resolved_at timestamptz NOT NULL,
    is_kpi_resolution boolean NOT NULL DEFAULT true,
    channel text,
    segment text,
    issue_code text
);

-- One row per source dataset, recording complete event-time coverage.
-- Coverage boundaries are needed to exclude right/left censored event windows.
CREATE TABLE IF NOT EXISTS stg_data_coverage (
    dataset_name text NOT NULL PRIMARY KEY,
    data_from_at timestamptz NOT NULL,
    data_through_at timestamptz NOT NULL,
    CHECK (data_through_at >= data_from_at)
);
