# CXSignal

**Customer Experience Driver & Service Recovery Analytics**

CXSignal is a business analytics project to identify the factors shaping customer experience, detect service failures, and help teams prioritize effective recovery actions.

## Project status

Day 1 foundation: project charter, repository structure, and initial documentation. No production data or analytical models are included yet.

## Goals

- Give CX leaders a clear view of experience outcomes and their drivers.
- Help Support identify and recover from customer-impacting service failures.
- Give Product evidence about experience friction and recurring product issues.
- Help Operations monitor service delivery, ownership, and recovery performance.

## Repository map

```text
cx-signal/
├── data/
│   ├── raw/          # Approved, access-controlled source extracts; never commit sensitive data
│   └── processed/    # Derived datasets; commit only synthetic or explicitly approved samples
├── docs/             # Charter, metric definitions, and project decisions
├── notebooks/        # Exploratory analysis
├── reports/          # Reviewed analysis outputs
├── src/cx_signal/    # Reusable analysis code
└── tests/            # Data and logic checks
```

## Getting started

This repository is a documentation and structure shell. Add environment setup and reproducible analysis instructions when the implementation stack and approved data sources are selected.

## Project charter

See [the CXSignal project charter](docs/project-charter.md) for personas, decisions, scope, exclusions, risks, data ownership, operating cadence, privacy principles, and acceptance criteria.

See the [CX KPI catalog and measurement policy](docs/kpi-catalog-and-measurement-policy.md) for KPI formulas, denominator rules, metric ownership, survey-linkage assumptions, and attribution limits.

See [CX data sources and dictionary](docs/data-sources-and-dictionary.md) for candidate source domains, logical fields, source grain, join-key guidance, and raw-data provenance controls.

See the [raw ingestion framework](docs/ingestion-framework.md) for manifest-driven CSV ingestion, schema validation, repeatable configurations, and synthetic fixtures.

See the [staging and identity policy](docs/staging-and-identity-policy.md) for normalization rules, conservative survey-service matching, and ambiguous-match quarantine.
