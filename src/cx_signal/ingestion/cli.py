"""Command-line entry point for manifest-driven CSV ingestion."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class IngestionError(Exception):
    """Raised when an input or ingestion configuration is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        config = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestionError(f"Cannot read JSON configuration {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise IngestionError("Configuration root must be a JSON object")
    for key in ("source_system", "source_domain", "schema_version", "columns"):
        if key not in config:
            raise IngestionError(f"Configuration is missing required key: {key}")
    if not isinstance(config["columns"], list) or not config["columns"]:
        raise IngestionError("Configuration 'columns' must be a non-empty list")
    names = [column.get("name") for column in config["columns"] if isinstance(column, dict)]
    if len(names) != len(config["columns"]) or any(not name for name in names):
        raise IngestionError("Each configured column must have a name")
    if len(names) != len(set(names)):
        raise IngestionError("Configured column names must be unique")
    supported_types = {"string", "integer", "number", "boolean", "date", "timestamp"}
    for column in config["columns"]:
        kind = column.get("type", "string")
        if kind not in supported_types:
            raise IngestionError(f"Unsupported configured type '{kind}' for column '{column['name']}'")
    source_system = config["source_system"]
    if not isinstance(source_system, str) or not source_system or source_system in {".", ".."}:
        raise IngestionError("source_system must be a non-empty safe path component")
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in source_system):
        raise IngestionError("source_system may contain only letters, digits, dot, underscore, and hyphen")
    return config, hashlib.sha256(raw).hexdigest()


def validate_value(value: str, kind: str, row_number: int, column: str) -> str | None:
    if value == "":
        return None
    try:
        if kind == "string":
            return None
        if kind == "integer":
            int(value)
        elif kind == "number":
            float(value)
        elif kind == "boolean":
            if value.lower() not in {"true", "false", "1", "0"}:
                raise ValueError("expected true, false, 1, or 0")
        elif kind == "date":
            datetime.strptime(value, "%Y-%m-%d")
        elif kind == "timestamp":
            normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                raise ValueError("timestamp must include a timezone")
        else:
            raise IngestionError(f"Unsupported configured type '{kind}' for column '{column}'")
    except ValueError as exc:
        raise IngestionError(f"Row {row_number}, column '{column}': {exc}") from exc
    return None


def validate_csv(path: Path, config: dict[str, Any]) -> tuple[int, list[str]]:
    configured = config["columns"]
    expected = [column["name"] for column in configured]
    required = {column["name"] for column in configured if column.get("required", False)}
    allow_extra = config.get("allow_extra_columns", False)
    row_count = 0
    try:
        with path.open("r", encoding=config.get("encoding", "utf-8-sig"), newline="") as stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames
            if not headers:
                raise IngestionError("CSV is empty or has no header row")
            if len(headers) != len(set(headers)):
                raise IngestionError("CSV contains duplicate column names")
            missing = sorted(set(expected) - set(headers))
            extra = sorted(set(headers) - set(expected))
            if missing:
                raise IngestionError(f"CSV is missing configured columns: {', '.join(missing)}")
            if extra and not allow_extra:
                raise IngestionError(f"CSV contains unconfigured columns: {', '.join(extra)}")
            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise IngestionError(f"Row {row_number} has more fields than the header")
                for column in configured:
                    name = column["name"]
                    value = row.get(name)
                    if value is None:
                        raise IngestionError(f"Row {row_number}, column '{name}' is missing")
                    if column.get("required", False) and value.strip() == "":
                        raise IngestionError(f"Row {row_number}, required column '{name}' is blank")
                    validate_value(value, column.get("type", "string"), row_number, name)
                row_count += 1
    except UnicodeDecodeError as exc:
        raise IngestionError(f"CSV cannot be decoded as {config.get('encoding', 'utf-8-sig')}: {exc}") from exc
    except OSError as exc:
        raise IngestionError(f"Cannot read input {path}: {exc}") from exc
    return row_count, expected


def ingest(input_path: Path, config_path: Path, raw_root: Path) -> Path:
    if not input_path.is_file():
        raise IngestionError(f"Input file does not exist: {input_path}")
    config, config_hash = load_config(config_path)
    row_count, headers = validate_csv(input_path, config)
    content_hash = sha256_file(input_path)
    source_system = str(config["source_system"])
    batch_id = hashlib.sha256(
        f"{source_system}\0{config_hash}\0{content_hash}".encode("utf-8")
    ).hexdigest()[:20]
    batch_dir = raw_root / source_system / batch_id
    stored_input = batch_dir / input_path.name
    manifest_path = batch_dir / "manifest.json"

    if batch_dir.exists():
        if not stored_input.is_file() or sha256_file(stored_input) != content_hash:
            raise IngestionError(f"Existing batch {batch_id} differs from this input; refusing to overwrite")
        if not manifest_path.is_file():
            raise IngestionError(f"Existing batch {batch_id} has no manifest; refusing to overwrite")
        print(f"Batch already ingested: {batch_dir}")
        return manifest_path

    batch_dir.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copyfile(input_path, stored_input)
        if sha256_file(stored_input) != content_hash:
            raise IngestionError("Copied raw input checksum does not match source checksum")
        manifest = {
            "manifest_version": 1,
            "batch_id": batch_id,
            "source_system": source_system,
            "source_domain": config["source_domain"],
            "source_owner": config.get("source_owner", "UNCONFIRMED"),
            "source_file_name": input_path.name,
            "source_file_sha256": content_hash,
            "stored_file": input_path.name,
            "stored_file_sha256": content_hash,
            "source_extracted_at": config.get("source_extracted_at", "UNCONFIRMED"),
            "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
            "schema_version": config["schema_version"],
            "config_sha256": config_hash,
            "row_count": row_count,
            "columns": headers,
            "encoding": config.get("encoding", "utf-8-sig"),
            "raw_input_unchanged": True,
            "sensitivity_classification": config.get("sensitivity_classification", "UNCONFIRMED"),
            "approval_reference": config.get("approval_reference", "UNCONFIRMED"),
            "retention_reference": config.get("retention_reference", "UNCONFIRMED"),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(batch_dir)
        raise
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and immutably archive a CXSignal CSV batch")
    parser.add_argument("--input", required=True, type=Path, help="CSV file to ingest")
    parser.add_argument("--config", required=True, type=Path, help="Version-controlled JSON source configuration")
    parser.add_argument("--raw-root", required=True, type=Path, help="Approved controlled raw storage location")
    args = parser.parse_args(argv)
    try:
        manifest = ingest(args.input, args.config, args.raw_root)
    except (IngestionError, OSError) as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 2
    print(f"Ingestion complete. Manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
