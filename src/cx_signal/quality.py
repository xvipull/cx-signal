"""Configurable data-quality checks and privacy-conscious report generation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cx_signal.ingestion.cli import IngestionError, sha256_file
from cx_signal.staging import StagingError, clean_customer_key, load_batch


class QualityError(Exception):
    """Raised when quality inputs or configuration cannot be read."""


def safe_ref(row: dict[str, str], fields: list[str]) -> str:
    raw = "|".join(row.get(field, "") for field in fields if row.get(field, ""))
    if not raw:
        return "row-unknown"
    return "row-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def read_manifested_batch(batch_dir: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    try:
        return load_batch(batch_dir)
    except StagingError as exc:
        raise QualityError(str(exc)) from exc


def parse_timestamp(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def add_issue(issues: list[dict[str, str]], severity: str, check: str,
              record_ref: str, field: str, reason: str) -> None:
    issues.append({"severity": severity, "check": check, "record_ref": record_ref,
                   "field": field, "reason": reason})


def check_required(rows: list[dict[str, str]], fields: list[str], dataset: str,
                   issues: list[dict[str, str]], ref_fields: list[str]) -> int:
    count = 0
    for row in rows:
        for field in fields:
            if not row.get(field, "").strip():
                add_issue(issues, "fail", "required_field", safe_ref(row, ref_fields), field,
                          f"{dataset} required field is blank")
                count += 1
    return count


def check_duplicates(rows: list[dict[str, str]], fields: list[str], dataset: str,
                     issues: list[dict[str, str]], ref_fields: list[str]) -> int:
    count = 0
    for field in fields:
        seen: set[str] = set()
        for row in rows:
            value = row.get(field, "").strip()
            if not value:
                continue
            if value in seen:
                add_issue(issues, "fail", "duplicate_interaction", safe_ref(row, ref_fields), field,
                          f"Duplicate {dataset} interaction key")
                count += 1
            else:
                seen.add(value)
    return count


def check_timestamps(rows: list[dict[str, str]], fields: list[str], dataset: str,
                     now: datetime, tolerance: timedelta, issues: list[dict[str, str]],
                     ref_fields: list[str]) -> int:
    count = 0
    for row in rows:
        for field in fields:
            raw = row.get(field, "").strip()
            if not raw:
                continue
            parsed = parse_timestamp(raw)
            if parsed is None:
                add_issue(issues, "fail", "impossible_timestamp", safe_ref(row, ref_fields), field,
                          f"{dataset} timestamp is invalid or lacks timezone")
                count += 1
            elif parsed > now + tolerance:
                add_issue(issues, "fail", "impossible_timestamp", safe_ref(row, ref_fields), field,
                          f"{dataset} timestamp is in the future")
                count += 1
        start, end = row.get("event_started_at", "").strip(), row.get("event_ended_at", "").strip()
        if start and end:
            parsed_start, parsed_end = parse_timestamp(start), parse_timestamp(end)
            if parsed_start and parsed_end and parsed_end < parsed_start:
                add_issue(issues, "fail", "impossible_timestamp", safe_ref(row, ref_fields),
                          "event_started_at,event_ended_at", "Event end precedes event start")
                count += 1
        created, resolved = row.get("case_created_at", "").strip(), row.get("case_resolved_at", "").strip()
        if created and resolved:
            parsed_created, parsed_resolved = parse_timestamp(created), parse_timestamp(resolved)
            if parsed_created and parsed_resolved and parsed_resolved < parsed_created:
                add_issue(issues, "fail", "impossible_timestamp", safe_ref(row, ref_fields),
                          "case_created_at,case_resolved_at", "Resolution precedes case creation")
                count += 1
    return count


def check_scores(rows: list[dict[str, str]], ranges: dict[str, list[int]],
                 issues: list[dict[str, str]]) -> int:
    count = 0
    for row in rows:
        if not row.get("response_value", "").strip():
            continue  # Counted by response-completeness check.
        question = row.get("question_id", "")
        bounds = ranges.get(question)
        if not bounds:
            add_issue(issues, "warn", "invalid_score", safe_ref(row, ["survey_response_id"]),
                      "question_id", "No approved score range configured for this question")
            count += 1
            continue
        try:
            score = float(row["response_value"])
        except ValueError:
            score = float("nan")
        if score != score or score < bounds[0] or score > bounds[1] or not score.is_integer():
            add_issue(issues, "fail", "invalid_score", safe_ref(row, ["survey_response_id"]),
                      "response_value", "Score is nonnumeric, noninteger, or outside configured range")
            count += 1
    return count


def input_age(manifest: dict[str, Any], dataset: str, max_age: timedelta,
              now: datetime, issues: list[dict[str, str]]) -> tuple[str, int]:
    raw = str(manifest.get("source_extracted_at", "")).strip()
    parsed = parse_timestamp(raw)
    if parsed is None:
        add_issue(issues, "warn", "stale_input", f"{dataset}-batch", "source_extracted_at",
                  "Extraction timestamp is missing or invalid")
        return "unknown", 1
    age = now - parsed
    hours = max(0, int(age.total_seconds() // 3600))
    if age > max_age:
        add_issue(issues, "warn", "stale_input", f"{dataset}-batch", "source_extracted_at",
                  f"Input exceeds freshness threshold ({hours} hours old)")
        return f"stale ({hours} hours)", 1
    if age < timedelta(0):
        add_issue(issues, "fail", "stale_input", f"{dataset}-batch", "source_extracted_at",
                  "Extraction timestamp is in the future")
        return "invalid future timestamp", 1
    return f"fresh ({hours} hours)", 0


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = ["severity", "check", "record_ref", "field", "reason"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# CXSignal data quality report", "",
        f"- **Generated:** {report['generated_at_utc']}",
        f"- **Policy:** `{report['policy_version']}`",
        f"- **Overall status:** **{report['overall_status']}**",
        f"- **Survey batch:** `{report['source_batches']['survey']}` ({report['freshness']['survey']})",
        f"- **Service batch:** `{report['source_batches']['service']}` ({report['freshness']['service']})", "",
        "## Dataset summary", "",
        "| Dataset | Rows | Complete responses | Completeness |", "|---|---:|---:|---:|",
        f"| Survey | {report['row_counts']['survey']} | {report['response_completeness']['complete']} | {report['response_completeness']['rate_percent']:.1f}% |",
        f"| Service | {report['row_counts']['service']} | — | — |", "",
        "## Check results", "",
        "| Check | Findings |", "|---|---:|",
    ]
    for check, count in report["check_counts"].items():
        lines.append(f"| {check.replace('_', ' ').title()} | {count} |")
    lines.extend(["", "## Issue summary", "",
                  f"- Errors: {report['issue_counts']['fail']}",
                  f"- Warnings: {report['issue_counts']['warn']}",
                  "- Record references in `quality_issues.csv` are one-way hashes; raw customer or interaction IDs are not included.",
                  "- This report is based on the input batches and policy version listed above. Stale or incomplete inputs limit interpretation.", ""])
    return "\n".join(lines)


def generate_report(survey_batch: Path, service_batch: Path, config_path: Path,
                    output_dir: Path, now: datetime | None = None) -> dict[str, Any]:
    try:
        policy = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualityError(f"Cannot read quality policy {config_path}: {exc}") from exc
    surveys, survey_manifest = read_manifested_batch(survey_batch)
    services, service_manifest = read_manifested_batch(service_batch)
    now = now or datetime.now(timezone.utc)
    issues: list[dict[str, str]] = []
    checks: dict[str, int] = {}
    checks["required_fields"] = check_required(surveys, policy["required_fields"]["survey"], "survey", issues, ["survey_response_id"])
    checks["required_fields"] += check_required(services, policy["required_fields"]["service"], "service", issues, ["service_event_id"])
    checks["duplicate_interactions"] = check_duplicates(services, policy["duplicate_keys"]["service"], "service", issues, ["service_event_id", "case_id"])
    checks["invalid_scores"] = check_scores(surveys, policy["score_ranges_by_question"], issues)
    tolerance = timedelta(minutes=int(policy.get("future_timestamp_tolerance_minutes", 0)))
    checks["impossible_timestamps"] = check_timestamps(surveys, policy["timestamp_fields"]["survey"], "survey", now, tolerance, issues, ["survey_response_id"])
    checks["impossible_timestamps"] += check_timestamps(services, policy["timestamp_fields"]["service"], "service", now, tolerance, issues, ["service_event_id", "case_id"])

    service_customers = {clean_customer_key(row.get("customer_key")) for row in services
                         if clean_customer_key(row.get("customer_key"))}
    orphan_rows = [row for row in surveys
                   if clean_customer_key(row.get("customer_key")) not in service_customers]
    for row in orphan_rows:
        add_issue(issues, "warn", "orphaned_customer", safe_ref(row, ["survey_response_id"]), "customer_key",
                  "Survey customer key has no corresponding service record in this batch")
    checks["orphaned_customers"] = len(orphan_rows)

    incomplete_fields = policy.get("incomplete_fields", {}).get("survey", [])
    incomplete = [row for row in surveys if any(not row.get(field, "").strip() for field in incomplete_fields)]
    for row in incomplete:
        add_issue(issues, "warn", "response_completeness", safe_ref(row, ["survey_response_id"]), ",".join(incomplete_fields),
                  "Survey response is missing one or more configured completeness fields")
    checks["response_incompleteness"] = len(incomplete)

    max_age = timedelta(days=int(policy["max_input_age_days"]))
    freshness = {}
    checks["stale_inputs"] = 0
    freshness["survey"], n = input_age(survey_manifest, "survey", max_age, now, issues)
    checks["stale_inputs"] += n
    freshness["service"], n = input_age(service_manifest, "service", max_age, now, issues)
    checks["stale_inputs"] += n

    counts = {severity: sum(issue["severity"] == severity for issue in issues) for severity in ("fail", "warn")}
    overall = "fail" if counts["fail"] else ("warn" if counts["warn"] else "pass")
    complete_count = len(surveys) - len(incomplete)
    report = {
        "report_version": 1,
        "generated_at_utc": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "policy_version": policy.get("policy_version", "UNVERSIONED"),
        "policy_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "overall_status": overall,
        "source_batches": {"survey": survey_manifest.get("batch_id"), "service": service_manifest.get("batch_id")},
        "freshness": freshness,
        "row_counts": {"survey": len(surveys), "service": len(services)},
        "response_completeness": {"complete": complete_count, "incomplete": len(incomplete),
                                  "rate_percent": (100 * complete_count / len(surveys)) if surveys else 0.0},
        "check_counts": checks,
        "issue_counts": counts,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "quality_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "quality_report.md").write_text(render_markdown(report), encoding="utf-8")
    write_csv(output_dir / "quality_issues.csv", issues)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run CXSignal quality checks on manifest-backed survey and service batches")
    parser.add_argument("--survey-batch", type=Path, required=True)
    parser.add_argument("--service-batch", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = generate_report(args.survey_batch, args.service_batch, args.config, args.output_dir)
    except (QualityError, IngestionError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"Quality report failed: {exc}", file=sys.stderr)
        return 2
    print(f"Quality status: {report['overall_status']}; report: {args.output_dir / 'quality_report.md'}")
    return 1 if report["overall_status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
