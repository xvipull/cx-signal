# Survey-service reconciliation report

- **Generated:** 2026-11-13T04:48:52.722943Z
- **Policy:** `survey-service-reconciliation-v1`
- **Overall threshold status:** **pass**

## Record disposition

| Record set | Total | Matched | Unmatched | Ambiguous |
|---|---:|---:|---:|---:|
| Survey | 3 | 2 | 0 | 1 |
| Service | 4 | 2 | 0 | 2 |

## Tolerance checks

| Rate | Actual | Rule | Threshold | Status |
|---|---:|---|---:|---|
| Survey Match Rate | 66.7% | >= | 60.0% | pass |
| Survey Unmatched Rate | 0.0% | <= | 25.0% | pass |
| Survey Ambiguous Rate | 33.3% | <= | 35.0% | pass |
| Service Match Rate | 50.0% | >= | 50.0% | pass |
| Service Unmatched Rate | 0.0% | <= | 25.0% | pass |
| Service Ambiguous Rate | 50.0% | <= | 55.0% | pass |

Record references in `linkage_audit.csv` are hashed. Review ambiguous and unmatched records with the source owners before using linked metrics.
