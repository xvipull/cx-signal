"""Build dimensional CX customer and interaction marts from derived CSV sources."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cx_signal.staging import StagingError, clean_customer_key
from cx_signal.taxonomy import IssueTaxonomy, TaxonomyError


class MartError(Exception):
    """Raised when source data cannot support the declared mart grain."""


def hash_key(namespace: str, value: str) -> str:
    return namespace + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def load_csv(path: Path, required: list[str]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise MartError(f"Source has no CSV header: {path}")
            missing = sorted(set(required) - set(reader.fieldnames))
            if missing:
                raise MartError(f"{path} is missing required fields: {', '.join(missing)}")
            return list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise MartError(f"Cannot read source {path}: {exc}") from exc


def parse_utc(value: str | None, field: str) -> datetime:
    raw = (value or "").strip()
    if not raw:
        raise MartError(f"Required timestamp '{field}' is blank")
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MartError(f"Invalid timestamp in '{field}': {raw}") from exc
    if parsed.tzinfo is None:
        raise MartError(f"Timestamp '{field}' must include a timezone: {raw}")
    return parsed.astimezone(timezone.utc)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(survey_path: Path, service_path: Path, complaint_path: Path, order_path: Path,
          resolution_path: Path, taxonomy_path: Path, output_dir: Path) -> dict[str, Any]:
    taxonomy = IssueTaxonomy.from_file(taxonomy_path)
    surveys = load_csv(survey_path, ["survey_response_id", "customer_key", "question_id", "response_value", "response_submitted_at"])
    services = load_csv(service_path, ["service_event_id", "customer_key", "event_at", "channel", "status_code"])
    complaints = load_csv(complaint_path, ["complaint_id", "customer_key", "complaint_at", "issue_label"])
    orders = load_csv(order_path, ["order_id", "customer_key", "order_at", "order_status"])
    resolutions = load_csv(resolution_path, ["resolution_id", "customer_key", "resolved_at", "resolution_code"])

    customers: dict[str, dict[str, Any]] = {}
    dates: dict[int, dict[str, Any]] = {}
    issues: dict[str, dict[str, Any]] = {}
    channels: dict[str, dict[str, Any]] = {}
    statuses: dict[str, dict[str, Any]] = {}

    def customer_sk(raw_key: str | None) -> str:
        normalized = clean_customer_key(raw_key)
        key = hash_key("customer_", normalized) if normalized else "customer_unknown"
        customers.setdefault(key, {"customer_sk": key, "identity_type": "pseudonymous" if normalized else "unknown"})
        return key

    def date_sk(value: str | None, field: str) -> int:
        day = parse_utc(value, field).date()
        key = int(day.strftime("%Y%m%d"))
        dates.setdefault(key, {"date_sk": key, "date": day.isoformat(), "year": day.year,
                                "quarter": (day.month - 1) // 3 + 1, "month": day.month,
                                "day": day.day, "weekday_iso": day.isoweekday()})
        return key

    def issue_mapping(label: str | None) -> tuple[str, str, float]:
        mapped = taxonomy.map_label(label)
        code = mapped["issue_code"] or "unknown_issue"
        issues.setdefault(code, {
            "issue_sk": code,
            "issue_code": code,
            "issue_level_1": mapped["issue_level_1"] or "unknown",
            "issue_level_2": mapped["issue_level_2"] or "unknown",
            "issue_level_3": mapped["issue_level_3"] or "unknown",
            "canonical_issue_label": mapped["canonical_issue_label"] or "Unknown / unmapped",
            "taxonomy_version": taxonomy.version,
        })
        return code, str(mapped["mapping_status"]), float(mapped["mapping_confidence"])

    def issue_sk(label: str | None) -> str:
        return issue_mapping(label)[0]

    def code_sk(store: dict[str, dict[str, Any]], namespace: str, value: str | None,
                field_name: str) -> str:
        normalized = " ".join((value or "").strip().casefold().split()) or "unknown"
        key = hash_key(namespace + "_", normalized)
        store.setdefault(key, {field_name + "_sk": key, field_name: normalized})
        return key

    survey_facts: list[dict[str, Any]] = []
    seen_survey: set[str] = set()
    for row in surveys:
        source_id = row["survey_response_id"].strip()
        if not source_id or source_id in seen_survey:
            raise MartError("Survey grain violation: survey_response_id is blank or duplicated")
        seen_survey.add(source_id)
        question = row["question_id"].strip()
        score_text = row["response_value"].strip()
        try:
            score: int | str = int(score_text)
        except ValueError:
            score = score_text
        survey_facts.append({
            "survey_response_sk": hash_key("survey_", source_id), "customer_sk": customer_sk(row.get("customer_key")),
            "response_date_sk": date_sk(row.get("response_submitted_at"), "response_submitted_at"),
            "question_id": question, "question_version": row.get("question_version", ""),
            "response_value": score, "survey_channel": row.get("survey_channel", ""),
            "source_sha256": hashlib.sha256(source_id.encode()).hexdigest(),
        })

    interaction_facts: list[dict[str, Any]] = []
    seen_interactions: set[str] = set()
    for row in services:
        source_id = row["service_event_id"].strip()
        if not source_id or source_id in seen_interactions:
            raise MartError("Service interaction grain violation: service_event_id is blank or duplicated")
        seen_interactions.add(source_id)
        mapped_issue, mapping_status, mapping_confidence = issue_mapping(row.get("issue_label"))
        interaction_facts.append({
            "interaction_sk": hash_key("interaction_", source_id),
            "customer_sk": customer_sk(row.get("customer_key")),
            "interaction_date_sk": date_sk(row.get("event_at"), "event_at"),
            "channel_sk": code_sk(channels, "channel", row.get("channel"), "channel"),
            "status_sk": code_sk(statuses, "status", row.get("status_code"), "status"),
            "issue_sk": mapped_issue, "issue_mapping_status": mapping_status,
            "issue_mapping_confidence": mapping_confidence,
            "case_sk": hash_key("case_", row.get("case_id", "").strip()) if row.get("case_id", "").strip() else "case_unknown",
            "source_sha256": hashlib.sha256(source_id.encode()).hexdigest(),
        })

    complaint_facts: list[dict[str, Any]] = []
    seen_complaints: set[str] = set()
    for row in complaints:
        source_id = row["complaint_id"].strip()
        if not source_id or source_id in seen_complaints:
            raise MartError("Complaint grain violation: complaint_id is blank or duplicated")
        seen_complaints.add(source_id)
        mapped_issue, mapping_status, mapping_confidence = issue_mapping(row.get("issue_label"))
        complaint_facts.append({
            "complaint_sk": hash_key("complaint_", source_id), "customer_sk": customer_sk(row.get("customer_key")),
            "complaint_date_sk": date_sk(row.get("complaint_at"), "complaint_at"),
            "issue_sk": mapped_issue, "issue_mapping_status": mapping_status,
            "issue_mapping_confidence": mapping_confidence,
            "case_sk": hash_key("case_", row.get("case_id", "").strip()) if row.get("case_id", "").strip() else "case_unknown",
            "source_sha256": hashlib.sha256(source_id.encode()).hexdigest(),
        })

    order_facts: list[dict[str, Any]] = []
    seen_orders: set[str] = set()
    for row in orders:
        source_id = row["order_id"].strip()
        if not source_id or source_id in seen_orders:
            raise MartError("Order grain violation: order_id is blank or duplicated")
        seen_orders.add(source_id)
        order_facts.append({
            "order_sk": hash_key("order_", source_id), "customer_sk": customer_sk(row.get("customer_key")),
            "order_date_sk": date_sk(row.get("order_at"), "order_at"),
            "status_sk": code_sk(statuses, "status", row.get("order_status"), "status"),
            "order_channel": row.get("order_channel", ""),
            "source_sha256": hashlib.sha256(source_id.encode()).hexdigest(),
        })

    resolution_facts: list[dict[str, Any]] = []
    seen_resolutions: set[str] = set()
    for row in resolutions:
        source_id = row["resolution_id"].strip()
        if not source_id or source_id in seen_resolutions:
            raise MartError("Resolution grain violation: resolution_id is blank or duplicated")
        seen_resolutions.add(source_id)
        mapped_issue, mapping_status, mapping_confidence = issue_mapping(row.get("issue_label"))
        resolution_facts.append({
            "resolution_sk": hash_key("resolution_", source_id), "customer_sk": customer_sk(row.get("customer_key")),
            "resolution_date_sk": date_sk(row.get("resolved_at"), "resolved_at"),
            "resolution_code": " ".join(row.get("resolution_code", "").strip().casefold().split()),
            "issue_sk": mapped_issue, "issue_mapping_status": mapping_status,
            "issue_mapping_confidence": mapping_confidence,
            "case_sk": hash_key("case_", row.get("case_id", "").strip()) if row.get("case_id", "").strip() else "case_unknown",
            "source_sha256": hashlib.sha256(source_id.encode()).hexdigest(),
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    tables: dict[str, tuple[list[dict[str, Any]], list[str]]] = {
        "dim_customer.csv": (list(customers.values()), ["customer_sk", "identity_type"]),
        "dim_date.csv": (list(dates.values()), ["date_sk", "date", "year", "quarter", "month", "day", "weekday_iso"]),
        "dim_issue.csv": (list(issues.values()), ["issue_sk", "issue_code", "issue_level_1", "issue_level_2", "issue_level_3", "canonical_issue_label", "taxonomy_version"]),
        "dim_channel.csv": (list(channels.values()), ["channel_sk", "channel"]),
        "dim_status.csv": (list(statuses.values()), ["status_sk", "status"]),
        "fact_survey_response.csv": (survey_facts, ["survey_response_sk", "customer_sk", "response_date_sk", "question_id", "question_version", "response_value", "survey_channel", "source_sha256"]),
        "fact_service_interaction.csv": (interaction_facts, ["interaction_sk", "customer_sk", "interaction_date_sk", "channel_sk", "status_sk", "issue_sk", "issue_mapping_status", "issue_mapping_confidence", "case_sk", "source_sha256"]),
        "fact_complaint.csv": (complaint_facts, ["complaint_sk", "customer_sk", "complaint_date_sk", "issue_sk", "issue_mapping_status", "issue_mapping_confidence", "case_sk", "source_sha256"]),
        "fact_order.csv": (order_facts, ["order_sk", "customer_sk", "order_date_sk", "status_sk", "order_channel", "source_sha256"]),
        "fact_resolution.csv": (resolution_facts, ["resolution_sk", "customer_sk", "resolution_date_sk", "resolution_code", "issue_sk", "issue_mapping_status", "issue_mapping_confidence", "case_sk", "source_sha256"]),
    }
    for filename, (rows, fields) in tables.items():
        write_csv(output_dir / filename, rows, fields)
    manifest = {
        "mart_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "taxonomy_version": taxonomy.version,
        "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (survey_path, service_path, complaint_path, order_path, resolution_path)},
        "row_counts": {Path(name).stem: len(rows) for name, (rows, _) in tables.items()},
        "output_sha256": {name: hashlib.sha256((output_dir / name).read_bytes()).hexdigest() for name in tables},
    }
    (output_dir / "mart_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build CXSignal dimensional customer and interaction marts")
    parser.add_argument("--surveys", type=Path, required=True)
    parser.add_argument("--service-interactions", type=Path, required=True)
    parser.add_argument("--complaints", type=Path, required=True)
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--resolutions", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = build(args.surveys, args.service_interactions, args.complaints, args.orders,
                         args.resolutions, args.taxonomy, args.output_dir)
    except (MartError, StagingError, TaxonomyError, OSError, KeyError, ValueError) as exc:
        print(f"Mart build failed: {exc}", file=sys.stderr)
        return 2
    print(f"CX marts built in {args.output_dir}; survey facts: {manifest['row_counts']['fact_survey_response']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
