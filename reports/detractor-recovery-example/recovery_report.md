# CXSignal detractor recovery report

- **As of (UTC):** 2026-11-16T06:46:49.345477Z
- **Policy:** `detractor-recovery-v1`
- **Initial detractors:** 1
- **Outreach window:** 7 calendar days after detractor response
- **Resolution window:** 30 calendar days after detractor response
- **Follow-up window:** 30 calendar days after resolution

## Outcomes

| Measure | Count | Rate |
|---|---:|---:|
| Any documented outreach | 1 | 100.0% |
| Outreach within window | 1 | 100.0% |
| Any documented resolution | 1 | 100.0% |
| Resolution within window | 1 | 100.0% |
| Follow-up score observed | 1 | 100.0% |
| Recovered among observed follow-ups | 1 | 100.0% |

## Recovery status counts

- `recovered`: 1

## Definition and limitations

A detractor is an initial valid NPS score from 0 through 6. Outreach and resolution are linked only by the explicit initial survey response ID in the action ledger. Outreach is timely when it occurs within 7 calendar days; resolution is timely within 30 calendar days. Recovery requires a logged outreach, a resolution after that outreach, and an explicitly linked NPS follow-up submitted within 30 calendar days after resolution with a score of 7 or higher. A lower valid score is `not_recovered`. Missing follow-up is unknown, not failure. A late resolution can still be marked recovered if the follow-up outcome qualifies; timeliness is reported separately.

The observed recovery rate uses only detractors with a qualifying post-resolution follow-up as its denominator. It is subject to follow-up response and linkage bias and is not an estimate of recovery among all detractors. Explicit action logging may be incomplete; unrecorded outreach/resolution appears absent. These calendar-day windows are proposed policy defaults and need CX, Support, and VoC approval. Synthetic example counts are not representative.
