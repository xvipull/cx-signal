# Detractor recovery tracking

**Policy:** `configs/recovery/detractor_recovery.v1.json`  
**Builder:** `python -m cx_signal.recovery`  
**Status:** Proposed operating windows; CX, Support, and VoC owners must approve before production use

The recovery tracker starts from valid NPS responses scored 0–6 and links actions and follow-up responses only through an explicit `initial_survey_response_id`. It does not infer recovery links from customer identity or timestamps. Output uses a one-way hashed detractor reference and omits customer keys and source response IDs.

## Timing and outcome rules

- **Outreach window:** first documented outreach must occur within 7 calendar days after the initial detractor response to count as timely. A later outreach is recorded as `late`; missing outreach is `pending` until the window expires and then `overdue`.
- **Resolution window:** first documented resolution must occur within 30 calendar days after the initial detractor response to count as timely. Later resolution is `late`; missing resolution is `pending` until the window expires and then `overdue`.
- **Follow-up window:** an explicitly linked NPS response must occur after the logged resolution and within 30 calendar days of that resolution. It must use the same NPS question ID and version as the initial score.
- **Recovered:** only when there is documented outreach, resolution occurs after outreach, and a valid in-window follow-up score is at least 7.
- **Not recovered:** the same eligible post-resolution follow-up score is 0–6.
- **Unknown/pending:** no follow-up is unknown, not failure. Status distinguishes pending from an expired follow-up window. A survey-version mismatch is reported as incomparable.
- **Late actions:** resolution timeliness and outcome recovery are separate. A late resolution may still count as recovered if its follow-up score meets the rule; the late resolution remains visible.

These are calendar-day defaults, not business-day SLAs. The outreach and resolution windows begin at the detractor survey response. The follow-up clock begins at resolution. Owners should approve these windows and definitions against the service-recovery process before production use.

## Input contracts

- Survey rows require `survey_response_id`, `question_id`, `question_version`, `response_value`, and timezone-aware `response_submitted_at`.
- Action rows require a unique `action_id`, `initial_survey_response_id`, `action_type` (`outreach` or `resolution`), and timezone-aware `event_at`. `outcome_code` is optional descriptive metadata.
- Follow-up rows require `followup_response_id`, `initial_survey_response_id`, `question_id`, `question_version`, `nps_score`, and timezone-aware `submitted_at`.
- Each action and follow-up must reference an actual NPS detractor response. The tool rejects absent/non-detractor references, invalid scores, duplicate follow-up IDs, unsupported action types, and actions after the as-of cutoff.
- Action and follow-up ledgers should be governed source records with documented ownership, access, and retention. Do not place direct identifiers or free-text notes in these files.

## Run with synthetic examples

```sh
PYTHONPATH=src python3 -m cx_signal.recovery \
  --surveys examples/fixtures/survey_responses.csv \
  --actions examples/fixtures/recovery_actions.csv \
  --followups examples/fixtures/recovery_followups.csv \
  --policy configs/recovery/detractor_recovery.v1.json \
  --output-dir reports/detractor-recovery-example
```

Use `--as-of` with an ISO 8601 timezone-aware timestamp to reproduce a historical status snapshot. The output includes `detractor_recovery.csv`, `recovery_summary.json`, and `recovery_report.md`. Outreach and resolution rates use all identified detractors as the denominator. Observed recovery rate uses only detractors with a valid linked post-resolution follow-up; the report also shows follow-up coverage.

## Limitations

Recovery rates are subject to follow-up response bias, incomplete action logging, linkage errors, and survivorship effects. Customers who respond may differ from those who do not. A higher subsequent score does not prove the outreach caused improvement; other events, regression to the mean, and survey changes may contribute. The method is descriptive and should not be used to score individual support agents or make automated consequential decisions.
