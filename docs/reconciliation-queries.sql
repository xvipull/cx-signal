-- Run against linkage_audit.csv loaded as a table named linkage_audit.
-- record_type: survey | service; disposition: matched | unmatched | ambiguous.

-- Overall record counts by side and disposition.
SELECT record_type, disposition, COUNT(*) AS record_count
FROM linkage_audit
GROUP BY record_type, disposition
ORDER BY record_type, disposition;

-- Survey records with no confirmed or ambiguous linkage.
SELECT record_ref, reason
FROM linkage_audit
WHERE record_type = 'survey' AND disposition = 'unmatched'
ORDER BY reason, record_ref;

-- Ambiguous surveys and their candidate service references.
SELECT record_ref AS survey_ref, reason, ambiguous_candidate_refs
FROM linkage_audit
WHERE record_type = 'survey' AND disposition = 'ambiguous'
ORDER BY reason, record_ref;

-- Service records that were not linked to any survey or considered as candidates.
SELECT record_ref, reason
FROM linkage_audit
WHERE record_type = 'service' AND disposition = 'unmatched'
ORDER BY record_ref;

-- Ambiguous service candidates and the survey references that produced ambiguity.
SELECT record_ref AS service_ref, ambiguous_candidate_refs
FROM linkage_audit
WHERE record_type = 'service' AND disposition = 'ambiguous'
ORDER BY record_ref;

-- A basic rate query; compute rates independently for surveys and services.
SELECT record_type,
       SUM(CASE WHEN disposition = 'matched' THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0) AS match_rate,
       SUM(CASE WHEN disposition = 'unmatched' THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0) AS unmatched_rate,
       SUM(CASE WHEN disposition = 'ambiguous' THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0) AS ambiguous_rate
FROM linkage_audit
GROUP BY record_type;
