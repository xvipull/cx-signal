# Raw ingestion framework

CXSignal's initial ingestion command accepts one CSV batch plus a version-controlled JSON configuration. It validates the configured header and field types before writing anything, copies the input byte-for-byte into a content-addressed batch directory, verifies the copied SHA-256, and writes a manifest alongside the raw file.

## Requirements

- Python 3.10 or newer; the implementation uses only the Python standard library.
- Raw output must go to an approved, access-controlled location outside this public repository. Do not point `--raw-root` at a tracked project directory for real data.

## Run the synthetic example

From the repository root:

```sh
python3 -m cx_signal.ingestion.cli \\
  --input examples/fixtures/survey_responses.csv \\
  --config configs/ingestion/survey_responses.v1.json \\
  --raw-root /path/to/approved/cxsignal-raw
```

For a local source checkout without installing the package, set the import path:

```sh
PYTHONPATH=src python3 -m cx_signal.ingestion.cli \\
  --input examples/fixtures/survey_responses.csv \\
  --config configs/ingestion/survey_responses.v1.json \\
  --raw-root /path/to/approved/cxsignal-raw
```

The tool prints the manifest path. A repeat run with identical source bytes and configuration resolves to the same batch ID; it verifies the archived checksum and exits without overwriting the existing batch. A changed file or config creates a different batch. A conflicting existing batch fails closed.

## Configuration

Each JSON source config is a versioned contract. It identifies the source domain/system, schema version, expected columns, field types, required values, encoding, and provenance metadata. Supported field types are `string`, `integer`, `number`, `boolean`, `date` (`YYYY-MM-DD`), and timezone-aware `timestamp` (ISO 8601). Extra CSV columns are rejected by default. Make a new config version when the source schema or approved mapping changes; do not edit a published config in place after using it to ingest a batch.

The manifest records source and stored checksums, row count, columns, config checksum, batch ID, schema version, source extraction time, ingestion time, and approval/sensitivity/retention references. Replace `UNCONFIRMED` metadata with owner-approved values for real sources. No credentials or direct identifiers belong in configuration or manifests.

## Raw preservation and scope

The source file is copied as-is; validation reads it but does not normalize or rewrite it. The ingestion layer does not clean, deduplicate, link, or transform records. Those operations belong in derived processing with separate code, lineage, and quality checks. Raw inputs and manifests for production data belong only in controlled storage, never in this public repository. The checked-in fixture is synthetic and exists solely to demonstrate the schema contract.

## Current limitations

This first version supports local CSV files and JSON configurations. It does not yet support databases, object-store connectors, secrets management, incremental extraction, compressed files, schema registry integration, malware scanning, or automated retention/deletion. Source-system approval, data access, and storage controls remain prerequisites for real data.
