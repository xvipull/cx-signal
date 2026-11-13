"""Survey/service linkage audit and threshold reconciliation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cx_signal.staging import StagingError, read_json


class ReconciliationError(Exception):
    """Raised when staging outputs or reconciliation policy are invalid."""


def ref(namespace: str, value: str) -> str:
    return namespace + "_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise ReconciliationError(f"CSV has no header: {path}")
            return list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ReconciliationError(f"Cannot read {path}: {exc}") from exc


def audit_linkage(surveys: list[dict[str, str]], services: list[dict[str, str]],
                  matches: list[dict[str, str]], quarantines: list[dict[str, str]],
                  thresholds: dict[str, float]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    surveys_by_id = {row.get("survey_response_id", ""): row for row in surveys}
    services_by_id = {row.get("service_event_id", ""): row for row in services}
    if "" in surveys_by_id or len(surveys_by_id) != len(surveys):
        raise ReconciliationError("Survey response IDs must be non-empty and unique for reconciliation")
    if "" in services_by_id or len(services_by_id) != len(services):
        raise ReconciliationError("Service event IDs must be non-empty and unique for reconciliation")

    confirmed_survey: dict[str, list[str]] = {key: [] for key in surveys_by_id}
    confirmed_service: dict[str, list[str]] = {key: [] for key in services_by_id}
    survey_methods: dict[str, list[str]] = {key: [] for key in surveys_by_id}
    service_methods: dict[str, list[str]] = {key: [] for key in services_by_id}
    ambiguous_surveys: dict[str, dict[str, Any]] = {}
    ambiguous_services: dict[str, list[str]] = {key: [] for key in services_by_id}
    unmatched_reason: dict[str, str] = {}

    for match in matches:
        survey_id, service_id = match.get("survey_response_id", ""), match.get("service_event_id", "")
        if survey_id not in surveys_by_id or service_id not in services_by_id:
            raise ReconciliationError("Match table references a survey or service absent from staged inputs")
        confirmed_survey[survey_id].append(service_id)
        confirmed_service[service_id].append(survey_id)
        method = match.get("match_method", "unknown")
        survey_methods[survey_id].append(method)
        service_methods[service_id].append(method)

    for item in quarantines:
        survey_id = item.get("survey_response_id", "")
        if survey_id not in surveys_by_id:
            raise ReconciliationError("Quarantine table references a survey absent from staged inputs")
        reason = item.get("quarantine_reason", "unmatched")
        if reason.startswith("multiple_"):
            try:
                candidate_ids = json.loads(item.get("candidate_service_event_ids", "[]"))
            except json.JSONDecodeError as exc:
                raise ReconciliationError(f"Malformed candidate list for survey {ref('survey', survey_id)}") from exc
            if not isinstance(candidate_ids, list):
                raise ReconciliationError("candidate_service_event_ids must be a JSON array")
            unknown = [candidate for candidate in candidate_ids if candidate not in services_by_id]
            if unknown:
                raise ReconciliationError("Ambiguous candidate list references absent service events")
            ambiguous_surveys[survey_id] = {"reason": reason, "candidates": candidate_ids}
            for candidate in candidate_ids:
                ambiguous_services[candidate].append(survey_id)
        else:
            unmatched_reason[survey_id] = reason

    audit_rows: list[dict[str, str]] = []
    survey_counts = {"matched": 0, "unmatched": 0, "ambiguous": 0}
    for survey_id in surveys_by_id:
        if survey_id in ambiguous_surveys:
            disposition = "ambiguous"
            reason = ambiguous_surveys[survey_id]["reason"]
            candidate_refs = [ref("service", item) for item in ambiguous_surveys[survey_id]["candidates"]]
        elif confirmed_survey[survey_id]:
            disposition, reason, candidate_refs = "matched", "", []
        else:
            disposition, reason, candidate_refs = "unmatched", unmatched_reason.get(survey_id, "missing_linkage_record"), []
        survey_counts[disposition] += 1
        audit_rows.append({
            "record_type": "survey", "record_ref": ref("survey", survey_id), "disposition": disposition,
            "matched_record_refs": json.dumps([ref("service", item) for item in confirmed_survey[survey_id]]),
            "match_methods": json.dumps(survey_methods[survey_id]),
            "ambiguous_candidate_refs": json.dumps(candidate_refs), "reason": reason,
        })

    service_counts = {"matched": 0, "unmatched": 0, "ambiguous": 0}
    for service_id in services_by_id:
        if ambiguous_services[service_id]:
            disposition = "ambiguous"
            reason = "candidate_for_ambiguous_survey"
        elif confirmed_service[service_id]:
            disposition, reason = "matched", ""
        else:
            disposition, reason = "unmatched", "no_survey_link"
        service_counts[disposition] += 1
        audit_rows.append({
            "record_type": "service", "record_ref": ref("service", service_id), "disposition": disposition,
            "matched_record_refs": json.dumps([ref("survey", item) for item in confirmed_service[service_id]]),
            "match_methods": json.dumps(service_methods[service_id]),
            "ambiguous_candidate_refs": json.dumps([ref("survey", item) for item in ambiguous_services[service_id]]),
            "reason": reason,
        })

    def rate(value: int, total: int) -> float:
        return value / total if total else 0.0

    survey_total, service_total = len(surveys), len(services)
    rates = {
        "survey_match_rate": rate(survey_counts["matched"], survey_total),
        "survey_unmatched_rate": rate(survey_counts["unmatched"], survey_total),
        "survey_ambiguous_rate": rate(survey_counts["ambiguous"], survey_total),
        "service_match_rate": rate(service_counts["matched"], service_total),
        "service_unmatched_rate": rate(service_counts["unmatched"], service_total),
        "service_ambiguous_rate": rate(service_counts["ambiguous"], service_total),
    }
    checks = {
        "survey_match_rate": {"actual": rates["survey_match_rate"], "operator": ">=", "threshold": thresholds["min_survey_match_rate"]},
        "survey_unmatched_rate": {"actual": rates["survey_unmatched_rate"], "operator": "<=", "threshold": thresholds["max_unmatched_survey_rate"]},
        "survey_ambiguous_rate": {"actual": rates["survey_ambiguous_rate"], "operator": "<=", "threshold": thresholds["max_survey_ambiguous_rate"]},
        "service_match_rate": {"actual": rates["service_match_rate"], "operator": ">=", "threshold": thresholds["min_service_match_rate"]},
        "service_unmatched_rate": {"actual": rates["service_unmatched_rate"], "operator": "<=", "threshold": thresholds["max_unmatched_service_rate"]},
        "service_ambiguous_rate": {"actual": rates["service_ambiguous_rate"], "operator": "<=", "threshold": thresholds["max_service_ambiguous_rate"]},
    }
    for check in checks.values():
        check["status"] = "pass" if ((check["actual"] >= check["threshold"]) if check["operator"] == ">="
                                     else (check["actual"] <= check["threshold"])) else "fail"
    summary = {
        "counts": {"survey": {"total": survey_total, **survey_counts},
                   "service": {"total": service_total, **service_counts}},
        "rates": rates,
        "threshold_checks": checks,
        "overall_status": "pass" if all(check["status"] == "pass" for check in checks.values()) else "fail",
    }
    return audit_rows, summary


def write_audit(path: Path, rows: list[dict[str, str]]) -> None:
    fields = ["record_type", "record_ref", "disposition", "matched_record_refs", "match_methods",
              "ambiguous_candidate_refs", "reason"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def render_report(summary: dict[str, Any]) -> str:
    lines = ["# Survey-service reconciliation report", "",
             f"- **Generated:** {summary['generated_at_utc']}",
             f"- **Policy:** `{summary['policy_version']}`",
             f"- **Overall threshold status:** **{summary['overall_status']}**", "",
             "## Record disposition", "",
             "| Record set | Total | Matched | Unmatched | Ambiguous |", "|---|---:|---:|---:|---:|"]
    for name in ("survey", "service"):
        counts = summary["counts"][name]
        lines.append(f"| {name.title()} | {counts['total']} | {counts['matched']} | {counts['unmatched']} | {counts['ambiguous']} |")
    lines.extend(["", "## Tolerance checks", "", "| Rate | Actual | Rule | Threshold | Status |", "|---|---:|---|---:|---|"])
    for name, check in summary["threshold_checks"].items():
        lines.append(f"| {name.replace('_', ' ').title()} | {check['actual']:.1%} | {check['operator']} | {check['threshold']:.1%} | {check['status']} |")
    lines.extend(["", "Record references in `linkage_audit.csv` are hashed. Review ambiguous and unmatched records with the source owners before using linked metrics.", ""])
    return "\n".join(lines)


def reconcile(staging_dir: Path, policy_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest = read_json(staging_dir / "manifest.json")
    policy = read_json(policy_path)
    thresholds = policy.get("thresholds", {})
    required = ("min_survey_match_rate", "max_unmatched_survey_rate", "max_survey_ambiguous_rate",
                "min_service_match_rate", "max_unmatched_service_rate", "max_service_ambiguous_rate")
    missing = [name for name in required if name not in thresholds]
    if missing:
        raise ReconciliationError(f"Threshold policy is missing: {', '.join(missing)}")
    for name in required:
        value = float(thresholds[name])
        if not 0 <= value <= 1:
            raise ReconciliationError(f"Threshold {name} must be between 0 and 1")
    surveys = read_csv(staging_dir / "staged_surveys.csv")
    services = read_csv(staging_dir / "staged_service_events.csv")
    matches = read_csv(staging_dir / "survey_service_matches.csv")
    quarantines = read_csv(staging_dir / "survey_match_quarantine.csv")
    audit_rows, summary = audit_linkage(surveys, services, matches, quarantines,
                                        {name: float(thresholds[name]) for name in required})
    output_dir.mkdir(parents=True, exist_ok=True)
    summary.update({
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "policy_version": policy.get("policy_version", "UNVERSIONED"),
        "source_staging_batch_id": manifest.get("staging_batch_id"),
        "source_policy_sha256": manifest.get("policy_sha256"),
        "thresholds": {name: float(thresholds[name]) for name in required},
    })
    write_audit(output_dir / "linkage_audit.csv", audit_rows)
    (output_dir / "reconciliation_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "reconciliation_report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit and reconcile survey-service linkage outcomes")
    parser.add_argument("--staging-dir", type=Path, required=True, help="Manifest-backed Day 5 staging output directory")
    parser.add_argument("--policy", type=Path, required=True, help="Reconciliation threshold policy JSON")
    parser.add_argument("--output-dir", type=Path, required=True, help="New report output directory")
    args = parser.parse_args(argv)
    try:
        summary = reconcile(args.staging_dir, args.policy, args.output_dir)
    except (ReconciliationError, StagingError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"Reconciliation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Reconciliation {summary['overall_status']}: {args.output_dir / 'reconciliation_report.md'}")
    return 0 if summary["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
