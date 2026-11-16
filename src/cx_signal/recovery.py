"""Transparent detractor outreach, resolution, and recovery tracking."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class RecoveryError(Exception):
    """Raised when recovery source data or policy is invalid."""


def parse_time(value: str | None, field: str) -> datetime:
    raw = (value or "").strip()
    if not raw:
        raise RecoveryError(f"Required timestamp '{field}' is blank")
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RecoveryError(f"Invalid ISO timestamp for '{field}': {raw}") from exc
    if parsed.tzinfo is None:
        raise RecoveryError(f"Timestamp '{field}' must include a timezone")
    return parsed.astimezone(timezone.utc)


def read_csv(path: Path, required: list[str]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise RecoveryError(f"CSV has no header: {path}")
            missing = sorted(set(required) - set(reader.fieldnames))
            if missing:
                raise RecoveryError(f"{path} is missing columns: {', '.join(missing)}")
            return list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise RecoveryError(f"Cannot read {path}: {exc}") from exc


def private_ref(value: str) -> str:
    return "detractor_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def evaluate_recovery(surveys: list[dict[str, str]], actions: list[dict[str, str]],
                      followups: list[dict[str, str]], policy: dict[str, Any],
                      as_of: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = ("nps_question_ids", "detractor_max_score", "nps_score_min", "nps_score_max",
                "recovered_min_score", "outreach_window_days", "resolution_window_days", "followup_window_days")
    missing = [key for key in required if key not in policy]
    if missing:
        raise RecoveryError(f"Recovery policy is missing: {', '.join(missing)}")
    for key in ("outreach_window_days", "resolution_window_days", "followup_window_days"):
        if int(policy[key]) <= 0:
            raise RecoveryError(f"{key} must be a positive number of days")
    if not (policy["nps_score_min"] <= policy["detractor_max_score"] < policy["recovered_min_score"] <= policy["nps_score_max"]):
        raise RecoveryError("NPS detractor and recovered score thresholds are inconsistent")
    as_of = as_of.astimezone(timezone.utc)
    nps_ids = set(policy["nps_question_ids"])
    index: dict[str, dict[str, Any]] = {}
    seen_nps_responses: set[str] = set()
    for row in surveys:
        if row.get("question_id") not in nps_ids:
            continue
        response_id = row.get("survey_response_id", "").strip()
        if not response_id:
            raise RecoveryError("NPS survey_response_id must be populated")
        if response_id in seen_nps_responses:
            raise RecoveryError("NPS survey response IDs must be unique")
        seen_nps_responses.add(response_id)
        try:
            score = int(row.get("response_value", ""))
        except ValueError as exc:
            raise RecoveryError(f"Invalid NPS score for survey reference {private_ref(response_id)}") from exc
        if not policy["nps_score_min"] <= score <= policy["nps_score_max"]:
            raise RecoveryError(f"NPS score outside configured scale for {private_ref(response_id)}")
        if score <= policy["detractor_max_score"]:
            if response_id in index:
                raise RecoveryError("Duplicate detractor survey response ID")
            index[response_id] = {
                "response_id": response_id,
                "question_version": row.get("question_version", "").strip(),
                "score": score,
                "submitted_at": parse_time(row.get("response_submitted_at"), "response_submitted_at"),
            }

    actions_by_survey: dict[str, list[dict[str, Any]]] = {}
    seen_action_ids: set[str] = set()
    for row in actions:
        action_id = row.get("action_id", "").strip()
        if not action_id or action_id in seen_action_ids:
            raise RecoveryError("Action IDs must be non-empty and unique")
        seen_action_ids.add(action_id)
        survey_id = row.get("initial_survey_response_id", "").strip()
        if survey_id not in index:
            raise RecoveryError(f"Recovery action references a non-detractor or absent survey: {private_ref(survey_id)}")
        kind = row.get("action_type", "").strip().casefold()
        if kind not in {"outreach", "resolution"}:
            raise RecoveryError(f"Unsupported recovery action type: {kind}")
        event_at = parse_time(row.get("event_at"), "event_at")
        if event_at > as_of:
            raise RecoveryError(f"Recovery action is after the evaluation cutoff: {private_ref(survey_id)}")
        actions_by_survey.setdefault(survey_id, []).append({
            "type": kind,
            "at": event_at,
            "outcome_code": row.get("outcome_code", "").strip(),
        })

    followups_by_survey: dict[str, list[dict[str, Any]]] = {}
    seen_followups: set[str] = set()
    incomparable_followups: set[str] = set()
    for row in followups:
        survey_id = row.get("initial_survey_response_id", "").strip()
        if survey_id not in index:
            raise RecoveryError(f"Follow-up references a non-detractor or absent survey: {private_ref(survey_id)}")
        followup_id = row.get("followup_response_id", "").strip()
        if not followup_id or followup_id in seen_followups:
            raise RecoveryError("Follow-up response IDs must be non-empty and unique")
        seen_followups.add(followup_id)
        if row.get("question_id") not in nps_ids:
            continue
        if row.get("question_version", "").strip() != index[survey_id]["question_version"]:
            incomparable_followups.add(survey_id)
            continue
        try:
            score = int(row.get("nps_score", ""))
        except ValueError as exc:
            raise RecoveryError(f"Invalid follow-up NPS score: {private_ref(followup_id)}") from exc
        if not policy["nps_score_min"] <= score <= policy["nps_score_max"]:
            raise RecoveryError(f"Follow-up NPS score outside configured scale: {private_ref(followup_id)}")
        followups_by_survey.setdefault(survey_id, []).append({
            "followup_id": followup_id, "score": score,
            "at": parse_time(row.get("submitted_at"), "submitted_at"),
            "question_version": row.get("question_version", ""),
        })

    rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    for survey_id, detractor in index.items():
        start = detractor["submitted_at"]
        actions_for_survey = actions_by_survey.get(survey_id, [])
        outreach = sorted((item for item in actions_for_survey if item["type"] == "outreach" and item["at"] >= start), key=lambda item: item["at"])
        resolutions = sorted((item for item in actions_for_survey if item["type"] == "resolution" and item["at"] >= start), key=lambda item: item["at"])
        outreach_item = outreach[0] if outreach else None
        resolution_item = resolutions[0] if resolutions else None
        outreach_due = start + timedelta(days=int(policy["outreach_window_days"]))
        resolution_due = start + timedelta(days=int(policy["resolution_window_days"]))
        if outreach_item:
            outreach_status = "within_window" if outreach_item["at"] <= outreach_due else "late"
        else:
            outreach_status = "overdue" if as_of > outreach_due else "pending"
        if resolution_item:
            resolution_status = "within_window" if resolution_item["at"] <= resolution_due else "late"
        else:
            resolution_status = "overdue" if as_of > resolution_due else "pending"

        eligible_followups: list[dict[str, Any]] = []
        prior_followup = False
        if resolution_item and outreach_item and resolution_item["at"] >= outreach_item["at"]:
            followup_due = resolution_item["at"] + timedelta(days=int(policy["followup_window_days"]))
            for item in followups_by_survey.get(survey_id, []):
                if item["at"] < resolution_item["at"]:
                    prior_followup = True
                elif item["at"] <= followup_due and item["at"] <= as_of:
                    eligible_followups.append(item)
        else:
            followup_due = None
        followup = min(eligible_followups, key=lambda item: item["at"]) if eligible_followups else None

        if outreach_item is None:
            recovery_status = "no_documented_outreach"
        elif resolution_item is None:
            recovery_status = "resolution_overdue" if as_of > resolution_due else "pending_resolution"
        elif resolution_item["at"] < outreach_item["at"]:
            recovery_status = "resolution_precedes_outreach"
        elif followup:
            recovery_status = "recovered" if followup["score"] >= policy["recovered_min_score"] else "not_recovered"
        elif survey_id in incomparable_followups:
            recovery_status = "incomparable_followup_version"
        elif followup_due and as_of > followup_due:
            recovery_status = "unknown_followup_window_expired"
        elif prior_followup:
            recovery_status = "awaiting_post_resolution_followup"
        else:
            recovery_status = "awaiting_followup"

        status_counts[recovery_status] = status_counts.get(recovery_status, 0) + 1
        rows.append({
            "detractor_ref": private_ref(survey_id),
            "initial_nps_score": detractor["score"],
            "initial_response_at_utc": start.isoformat().replace("+00:00", "Z"),
            "outreach_status": outreach_status,
            "first_outreach_at_utc": outreach_item["at"].isoformat().replace("+00:00", "Z") if outreach_item else "",
            "outreach_days_from_detractor": (outreach_item["at"] - start).total_seconds() / 86400 if outreach_item else "",
            "resolution_status": resolution_status,
            "first_resolution_at_utc": resolution_item["at"].isoformat().replace("+00:00", "Z") if resolution_item else "",
            "resolution_days_from_detractor": (resolution_item["at"] - start).total_seconds() / 86400 if resolution_item else "",
            "followup_nps_score": followup["score"] if followup else "",
            "followup_at_utc": followup["at"].isoformat().replace("+00:00", "Z") if followup else "",
            "recovery_status": recovery_status,
        })

    outreach_count = sum(row["outreach_status"] in {"within_window", "late"} for row in rows)
    timely_outreach_count = sum(row["outreach_status"] == "within_window" for row in rows)
    resolution_count = sum(row["resolution_status"] in {"within_window", "late"} for row in rows)
    timely_resolution_count = sum(row["resolution_status"] == "within_window" for row in rows)
    observed_followup_count = sum(bool(row["followup_at_utc"]) for row in rows)
    recovered_count = sum(row["recovery_status"] == "recovered" for row in rows)
    report = {
        "as_of_utc": as_of.isoformat().replace("+00:00", "Z"),
        "detractor_count": len(rows),
        "outreach_count": outreach_count,
        "outreach_rate_percent": 100 * outreach_count / len(rows) if rows else None,
        "timely_outreach_count": timely_outreach_count,
        "timely_outreach_rate_percent": 100 * timely_outreach_count / len(rows) if rows else None,
        "resolution_count": resolution_count,
        "resolution_rate_percent": 100 * resolution_count / len(rows) if rows else None,
        "timely_resolution_count": timely_resolution_count,
        "timely_resolution_rate_percent": 100 * timely_resolution_count / len(rows) if rows else None,
        "followup_count": observed_followup_count,
        "followup_coverage_percent": 100 * observed_followup_count / len(rows) if rows else None,
        "recovered_count": recovered_count,
        "observed_recovery_rate_percent": 100 * recovered_count / observed_followup_count if observed_followup_count else None,
        "recovery_status_counts": status_counts,
    }
    return rows, report


def write_outputs(rows: list[dict[str, Any]], report: dict[str, Any], output_dir: Path,
                  policy: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else [
        "detractor_ref", "initial_nps_score", "initial_response_at_utc", "outreach_status",
        "first_outreach_at_utc", "outreach_days_from_detractor", "resolution_status",
        "first_resolution_at_utc", "resolution_days_from_detractor", "followup_nps_score",
        "followup_at_utc", "recovery_status",
    ]
    with (output_dir / "detractor_recovery.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    report["policy_version"] = policy.get("policy_version", "UNVERSIONED")
    report["windows_calendar_days"] = {
        "outreach": int(policy["outreach_window_days"]),
        "resolution": int(policy["resolution_window_days"]),
        "followup_after_resolution": int(policy["followup_window_days"]),
    }
    (output_dir / "recovery_summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# CXSignal detractor recovery report", "",
        f"- **As of (UTC):** {report['as_of_utc']}",
        f"- **Policy:** `{report['policy_version']}`",
        f"- **Initial detractors:** {report['detractor_count']}",
        f"- **Outreach window:** {report['windows_calendar_days']['outreach']} calendar days after detractor response",
        f"- **Resolution window:** {report['windows_calendar_days']['resolution']} calendar days after detractor response",
        f"- **Follow-up window:** {report['windows_calendar_days']['followup_after_resolution']} calendar days after resolution", "",
        "## Outcomes", "",
        "| Measure | Count | Rate |", "|---|---:|---:|",
        f"| Any documented outreach | {report['outreach_count']} | {fmt_rate(report['outreach_rate_percent'])} |",
        f"| Outreach within window | {report['timely_outreach_count']} | {fmt_rate(report['timely_outreach_rate_percent'])} |",
        f"| Any documented resolution | {report['resolution_count']} | {fmt_rate(report['resolution_rate_percent'])} |",
        f"| Resolution within window | {report['timely_resolution_count']} | {fmt_rate(report['timely_resolution_rate_percent'])} |",
        f"| Follow-up score observed | {report['followup_count']} | {fmt_rate(report['followup_coverage_percent'])} |",
        f"| Recovered among observed follow-ups | {report['recovered_count']} | {fmt_rate(report['observed_recovery_rate_percent'])} |", "",
        "## Recovery status counts", "",
    ]
    lines.extend(f"- `{status}`: {count}" for status, count in sorted(report["recovery_status_counts"].items()))
    lines.extend(["", "## Definition and limitations", "",
                  "A detractor is an initial valid NPS score from 0 through 6. Outreach and resolution are linked only by the explicit initial survey response ID in the action ledger. Outreach is timely when it occurs within 7 calendar days; resolution is timely within 30 calendar days. Recovery requires a logged outreach, a resolution after that outreach, and an explicitly linked NPS follow-up submitted within 30 calendar days after resolution with a score of 7 or higher. A lower valid score is `not_recovered`. Missing follow-up is unknown, not failure. A late resolution can still be marked recovered if the follow-up outcome qualifies; timeliness is reported separately.",
                  "",
                  "The observed recovery rate uses only detractors with a qualifying post-resolution follow-up as its denominator. It is subject to follow-up response and linkage bias and is not an estimate of recovery among all detractors. Explicit action logging may be incomplete; unrecorded outreach/resolution appears absent. These calendar-day windows are proposed policy defaults and need CX, Support, and VoC approval. Synthetic example counts are not representative.", ""])
    (output_dir / "recovery_report.md").write_text("\n".join(lines), encoding="utf-8")


def fmt_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Track detractor outreach, resolution, and recovery outcomes")
    parser.add_argument("--surveys", type=Path, required=True, help="Survey response CSV")
    parser.add_argument("--actions", type=Path, required=True, help="Explicitly linked outreach/resolution action CSV")
    parser.add_argument("--followups", type=Path, required=True, help="Explicitly linked follow-up NPS CSV")
    parser.add_argument("--policy", type=Path, required=True, help="Versioned recovery windows and score policy")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of", type=str, help="Evaluation cutoff timestamp (ISO 8601 with timezone); defaults to current UTC")
    args = parser.parse_args(argv)
    try:
        surveys = read_csv(args.surveys, ["survey_response_id", "question_id", "question_version", "response_value", "response_submitted_at"])
        actions = read_csv(args.actions, ["action_id", "initial_survey_response_id", "action_type", "event_at"])
        followups = read_csv(args.followups, ["followup_response_id", "initial_survey_response_id", "question_id", "question_version", "nps_score", "submitted_at"])
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        if not isinstance(policy, dict):
            raise RecoveryError("Recovery policy JSON root must be an object")
        as_of = parse_time(args.as_of, "as_of") if args.as_of else datetime.now(timezone.utc)
        rows, report = evaluate_recovery(surveys, actions, followups, policy, as_of)
        write_outputs(rows, report, args.output_dir, policy)
    except (RecoveryError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"Recovery tracking failed: {exc}", file=sys.stderr)
        return 2
    print(f"Tracked {report['detractor_count']} detractors; report: {args.output_dir / 'recovery_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
