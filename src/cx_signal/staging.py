"""Manifest-verified staging and conservative survey-to-service matching."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cx_signal.ingestion.cli import IngestionError, sha256_file


class StagingError(Exception):
    """Raised when staged inputs or policy are invalid."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StagingError(f"Cannot read JSON file {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StagingError(f"Expected a JSON object in {path}")
    return value


def load_batch(batch_dir: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    manifest_path = batch_dir / "manifest.json"
    manifest = read_json(manifest_path)
    filename = manifest.get("stored_file")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise StagingError(f"Manifest has an unsafe or missing stored_file: {manifest_path}")
    source = batch_dir / filename
    if not source.is_file() or sha256_file(source) != manifest.get("stored_file_sha256"):
        raise StagingError(f"Stored input is missing or its checksum differs from manifest: {source}")
    try:
        with source.open("r", encoding=manifest.get("encoding", "utf-8-sig"), newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise StagingError(f"No CSV header in {source}")
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise StagingError(f"Cannot read manifest input {source}: {exc}") from exc
    if len(rows) != manifest.get("row_count"):
        raise StagingError(f"Row count differs from manifest for {source}")
    return rows, manifest


def clean_identifier(value: str | None) -> str:
    """Trim surrounding whitespace while preserving opaque ID case and punctuation."""
    return (value or "").strip()


def clean_customer_key(value: str | None) -> str:
    """Normalize approved pseudonymous keys for case/space-insensitive joins."""
    return re.sub(r"\s+", "", (value or "").strip()).casefold()


def clean_timestamp(value: str | None, field: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise StagingError(f"Required timestamp '{field}' is blank")
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise StagingError(f"Invalid ISO timestamp in '{field}': {raw}") from exc
    if parsed.tzinfo is None:
        raise StagingError(f"Timestamp '{field}' must include a timezone: {raw}")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def clean_date(value: str | None, field: str) -> str:
    raw = (value or "").strip()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise StagingError(f"Invalid date in '{field}'; expected YYYY-MM-DD: {raw}") from exc


def normalize_code(value: str | None, aliases: dict[str, str]) -> tuple[str, str]:
    raw = re.sub(r"\s+", " ", (value or "").strip().casefold())
    if not raw:
        return "unknown", "blank"
    if raw in aliases:
        return aliases[raw], "mapped"
    return f"unmapped:{raw}", "unmapped"


def clean_rows(rows: list[dict[str, str]], identifiers: list[str], customer_field: str,
               time_field: str, channel_aliases: dict[str, str] | None = None,
               status_aliases: dict[str, str] | None = None,
               date_fields: list[str] | None = None) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row_number, original in enumerate(rows, start=1):
        row = {key: (value or "").strip() for key, value in original.items()}
        for key in identifiers:
            if key in row:
                row[key] = clean_identifier(row[key])
        row[customer_field] = clean_customer_key(row.get(customer_field))
        row[time_field] = clean_timestamp(row.get(time_field), time_field)
        for field in date_fields or []:
            if field in row and row[field].strip():
                row[field] = clean_date(row[field], field)
        if channel_aliases is not None:
            row["channel_raw_normalized"] = re.sub(r"\s+", " ", row.get("channel", "").strip().casefold())
            row["channel"], row["channel_mapping_status"] = normalize_code(row.get("channel"), channel_aliases)
        if status_aliases is not None:
            row["status_raw_normalized"] = re.sub(r"\s+", " ", row.get("status_code", "").strip().casefold())
            row["status_code"], row["status_mapping_status"] = normalize_code(row.get("status_code"), status_aliases)
        row["_source_row_number"] = str(row_number)
        result.append(row)
    return result


def match_surveys(surveys: list[dict[str, str]], services: list[dict[str, str]], policy: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    service_ids = policy["service_identifier_fields"]
    survey_ids = policy["survey_identifier_fields"]
    customer_field = policy["customer_key_field"]
    survey_time = policy["survey_time_field"]
    service_time = policy["service_time_field"]
    window = timedelta(days=int(policy["matching_window_days"]))
    index: dict[tuple[str, str], list[dict[str, str]]] = {}
    for service in services:
        for field in service_ids:
            key = service.get(field, "")
            if key:
                index.setdefault((field, key), []).append(service)
    matches: list[dict[str, str]] = []
    quarantine: list[dict[str, str]] = []
    for survey in surveys:
        candidates: dict[str, tuple[dict[str, str], str]] = {}
        for field in survey_ids:
            key = survey.get(field, "")
            if key and field in service_ids:
                for service in index.get((field, key), []):
                    candidates[service["_source_row_number"]] = (service, f"explicit:{field}")
        if len(candidates) == 1:
            service, method = next(iter(candidates.values()))
            matches.append(match_record(survey, service, method))
            continue
        if len(candidates) > 1:
            quarantine.append(quarantine_record(survey, "multiple_explicit_service_matches"))
            continue

        customer_key = survey.get(customer_field, "")
        if not customer_key:
            quarantine.append(quarantine_record(survey, "missing_customer_key"))
            continue
        response_at = datetime.fromisoformat(clean_timestamp(survey.get(survey_time), survey_time).replace("Z", "+00:00"))
        temporal_candidates = []
        for service in services:
            if service.get(customer_field) != customer_key:
                continue
            event_at = datetime.fromisoformat(clean_timestamp(service.get(service_time), service_time).replace("Z", "+00:00"))
            if event_at <= response_at and response_at - event_at <= window:
                temporal_candidates.append(service)
        if len(temporal_candidates) == 1:
            matches.append(match_record(survey, temporal_candidates[0], "unique_customer_time_window"))
        elif len(temporal_candidates) > 1:
            quarantine.append(quarantine_record(survey, "multiple_customer_time_window_matches"))
        else:
            quarantine.append(quarantine_record(survey, "no_eligible_service_match"))
    return matches, quarantine


def match_record(survey: dict[str, str], service: dict[str, str], method: str) -> dict[str, str]:
    return {
        "survey_response_id": survey.get("survey_response_id", ""),
        "service_event_id": service.get("service_event_id", ""),
        "case_id": service.get("case_id", ""), "order_id": service.get("order_id", ""),
        "match_method": method, "survey_source_row": survey["_source_row_number"],
        "service_source_row": service["_source_row_number"],
    }


def quarantine_record(survey: dict[str, str], reason: str) -> dict[str, str]:
    return {"survey_response_id": survey.get("survey_response_id", ""),
            "survey_source_row": survey["_source_row_number"], "quarantine_reason": reason}


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    if not fields:
        fields = ["no_rows"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def stage(survey_batch: Path, service_batch: Path, config_path: Path, output_root: Path) -> Path:
    policy_bytes = config_path.read_bytes()
    policy = read_json(config_path)
    required_policy = ("survey_time_field", "service_time_field", "survey_identifier_fields",
                       "service_identifier_fields", "customer_key_field", "matching_window_days")
    missing_policy = [key for key in required_policy if key not in policy]
    if missing_policy:
        raise StagingError(f"Matching policy is missing keys: {', '.join(missing_policy)}")
    if int(policy["matching_window_days"]) <= 0:
        raise StagingError("matching_window_days must be a positive integer")
    policy_hash = hashlib.sha256(policy_bytes).hexdigest()
    survey_raw, survey_manifest = load_batch(survey_batch)
    service_raw, service_manifest = load_batch(service_batch)
    customer_field = policy["customer_key_field"]
    surveys = clean_rows(survey_raw, policy["survey_identifier_fields"], customer_field,
                         policy["survey_time_field"])
    services = clean_rows(service_raw, policy["service_identifier_fields"], customer_field,
                          policy["service_time_field"], policy.get("channel_aliases", {}),
                          policy.get("status_aliases", {}), policy.get("date_fields", []))
    matches, quarantined = match_surveys(surveys, services, policy)
    batch_hash = hashlib.sha256(
        f"{survey_manifest['stored_file_sha256']}\0{service_manifest['stored_file_sha256']}\0{policy_hash}".encode()
    ).hexdigest()[:20]
    output_dir = output_root / batch_hash
    if output_dir.exists():
        raise StagingError(f"Staging output already exists; refusing to overwrite: {output_dir}")
    output_dir.mkdir(parents=True)
    try:
        for rows in (surveys, services):
            for row in rows:
                row.pop("_source_row_number", None)
        outputs = {
            "staged_surveys.csv": surveys,
            "staged_service_events.csv": services,
            "survey_service_matches.csv": matches,
            "survey_match_quarantine.csv": quarantined,
        }
        for filename, rows in outputs.items():
            write_csv(output_dir / filename, rows)
        manifest = {
            "manifest_version": 1, "staging_batch_id": batch_hash,
            "policy_version": policy.get("policy_version", "UNVERSIONED"),
            "policy_sha256": policy_hash,
            "source_batches": {"survey": survey_manifest.get("batch_id"), "service": service_manifest.get("batch_id")},
            "source_sha256": {"survey": survey_manifest.get("stored_file_sha256"), "service": service_manifest.get("stored_file_sha256")},
            "counts": {"survey_rows": len(surveys), "service_rows": len(services),
                       "matched_surveys": len(matches), "quarantined_surveys": len(quarantined)},
            "output_sha256": {filename: sha256_file(output_dir / filename) for filename in outputs},
        }
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        for path in output_dir.iterdir():
            path.unlink()
        output_dir.rmdir()
        raise
    return output_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage manifest-backed CX survey and service batches")
    parser.add_argument("--survey-batch", type=Path, required=True, help="Raw survey batch directory")
    parser.add_argument("--service-batch", type=Path, required=True, help="Raw service-event batch directory")
    parser.add_argument("--config", type=Path, required=True, help="Versioned staging and matching policy JSON")
    parser.add_argument("--output-root", type=Path, required=True, help="Derived staging output directory")
    args = parser.parse_args(argv)
    try:
        output_dir = stage(args.survey_batch, args.service_batch, args.config, args.output_root)
    except (StagingError, IngestionError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"Staging failed: {exc}", file=sys.stderr)
        return 2
    print(f"Staging complete: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
