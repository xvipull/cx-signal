# EDA and service diagnostics

The Day 11 EDA script generates purposeful charts and a written summary from the checked-in synthetic fixtures. It examines score distributions, field missingness, service/order channel mix, UTC contact timing, governed issue mix, status mix, and observed interaction-to-resolution lag.

## Run

Install the optional plotting dependency and run from the repository root:

```sh
python3 -m pip install -r requirements-eda.txt
PYTHONPATH=src python3 -m cx_signal.eda
```

The default output is `reports/eda-example/`. Override input/output locations with `--fixtures-dir`, `--taxonomy`, and `--output-dir`.

## Outputs

- `score_distributions.png`: separate NPS and CSAT score distributions.
- `missingness.png`: configured field missingness by source.
- `channel_segments.png`: service and order channel counts plus a visible product-segmentation availability panel.
- `contact_timing.png`: interaction counts by UTC weekday and hour.
- `issue_mix.png`: taxonomy-mapped labels, complaint categories, and resolution categories shown separately.
- `operational_drivers.png`: service status counts and observed event-to-resolution lag proxy.
- `eda_summary.md` / `eda_summary.json`: sample sizes, observed statistics, and interpretation limits.

## Findings and limits

The current examples contain only three survey rows, four service events, two complaints, three orders, and two resolutions. Their values are useful for demonstrating the analysis path, not for drawing conclusions about customer populations or operational performance. There is no product identifier, so product-segment analysis is unavailable. Surveys have no channel field and one survey has ambiguous service linkage, so score attribution by channel or service event is unsupported. The event-to-resolution chart measures time from the earliest recorded interaction for the case because the sample has no case-created timestamp; it is not the official resolution-time KPI. Issue records can overlap across source examples and are shown by source rather than deduplicated. Charts use UTC timestamps, not local operational calendars.

The script reports descriptive patterns and does not infer causal operational drivers. Use approved production data, validated linkage, representative samples, and a reviewed evaluation design before making prioritization or impact claims.
