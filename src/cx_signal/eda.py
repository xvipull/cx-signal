"""Generate descriptive CX EDA charts from the checked-in synthetic fixtures."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from cx_signal.staging import normalize_code
from cx_signal.taxonomy import IssueTaxonomy


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def parse_time(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone: {value}")
    return parsed.astimezone(timezone.utc)


def save_score_chart(surveys: list[dict[str, str]], output: Path) -> dict[str, Any]:
    scores: dict[str, list[int]] = defaultdict(list)
    for row in surveys:
        try:
            scores[row["question_id"]].append(int(row["response_value"]))
        except (ValueError, KeyError):
            continue
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    specs = [("NPS-v1", 0, 10, "NPS response score"), ("CSAT-v2", 1, 5, "CSAT response score")]
    result: dict[str, Any] = {}
    for ax, (question, low, high, title) in zip(axes, specs):
        values = scores.get(question, [])
        counts = Counter(values)
        xs = list(range(low, high + 1))
        ax.bar(xs, [counts.get(x, 0) for x in xs], color="#3b82f6")
        ax.set(title=f"{title} (n={len(values)})", xlabel="Score", ylabel="Responses")
        ax.set_xticks(xs)
        ax.grid(axis="y", alpha=0.25)
        if question == "NPS-v1" and values:
            promoters = sum(value >= 9 for value in values)
            detractors = sum(value <= 6 for value in values)
            nps = 100 * (promoters - detractors) / len(values)
            result["nps"] = {"valid_responses": len(values), "promoters": promoters,
                             "detractors": detractors, "nps_points": nps}
        elif question == "CSAT-v2" and values:
            satisfied = sum(value >= 4 for value in values)
            result["csat"] = {"valid_responses": len(values), "satisfied": satisfied,
                              "satisfied_percent": 100 * satisfied / len(values)}
    fig.suptitle("Synthetic survey score distributions")
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return result


def save_missingness_chart(tables: dict[str, list[dict[str, str]]], output: Path) -> dict[str, Any]:
    fields = {
        "Survey": ["customer_key", "question_id", "response_value", "response_submitted_at"],
        "Service": ["customer_key", "channel", "status_code", "event_at"],
        "Complaints": ["customer_key", "issue_label", "complaint_at", "case_id"],
        "Orders": ["customer_key", "order_status", "order_at", "order_channel"],
        "Resolutions": ["customer_key", "resolution_code", "resolved_at", "case_id"],
        "Issue label examples": ["case_id", "issue_label"],
    }
    labels, rates, summary = [], [], {}
    for table_name, columns in fields.items():
        rows = tables[table_name]
        for column in columns:
            missing = sum(not row.get(column, "").strip() for row in rows)
            rate = 100 * missing / len(rows) if rows else 0.0
            labels.append(f"{table_name}: {column}")
            rates.append(rate)
            summary[f"{table_name}.{column}"] = {"missing": missing, "rows": len(rows), "percent": rate}
    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    colors = ["#dc2626" if value else "#16a34a" for value in rates]
    ax.barh(labels, rates, color=colors)
    ax.set(xlabel="Missing values (%)", title="Field missingness by synthetic source")
    ax.set_xlim(0, 100)
    ax.grid(axis="x", alpha=0.25)
    for index, value in enumerate(rates):
        ax.text(value + 1, index, f"{value:.0f}%", va="center", fontsize=8)
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return summary


def save_channel_chart(services: list[dict[str, str]], orders: list[dict[str, str]],
                       aliases: dict[str, str], output: Path) -> dict[str, Any]:
    contact_counts = Counter(normalize_code(row.get("channel"), aliases)[0] for row in services)
    order_counts = Counter(" ".join(row.get("order_channel", "").strip().casefold().split()) or "unknown" for row in orders)
    categories = sorted(set(contact_counts) | set(order_counts))
    x = list(range(len(categories)))
    width = 0.38
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), constrained_layout=True)
    ax = axes[0]
    ax.bar([item - width / 2 for item in x], [contact_counts[key] for key in categories], width,
           label="Service interactions", color="#2563eb")
    ax.bar([item + width / 2 for item in x], [order_counts[key] for key in categories], width,
           label="Orders", color="#f59e0b")
    ax.set_xticks(x, categories, rotation=20, ha="right")
    ax.set_ylabel("Records")
    ax.set_title("Channel mix (source counts)")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    axes[1].axis("off")
    axes[1].text(0.5, 0.58, "Product segmentation unavailable", ha="center", va="center",
                 fontsize=12, weight="bold", transform=axes[1].transAxes)
    axes[1].text(0.5, 0.40, "No product identifier or product field\nin the synthetic source fixtures",
                 ha="center", va="center", transform=axes[1].transAxes)
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return {"service_interactions": dict(contact_counts), "orders": dict(order_counts)}


def save_timing_chart(services: list[dict[str, str]], output: Path) -> dict[str, Any]:
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_counts, hour_counts = Counter(), Counter()
    for row in services:
        timestamp = parse_time(row["event_at"])
        day_counts[timestamp.weekday()] += 1
        hour_counts[timestamp.hour] += 1
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    axes[0].bar(range(7), [day_counts[index] for index in range(7)], color="#0f766e")
    axes[0].set(xticks=range(7), xticklabels=weekdays, title="Contacts by UTC weekday", ylabel="Interactions")
    axes[1].bar(range(24), [hour_counts[index] for index in range(24)], color="#7c3aed")
    axes[1].set(xticks=range(0, 24, 2), title="Contacts by UTC hour", xlabel="Hour of day")
    for ax in axes:
        ax.grid(axis="y", alpha=0.25)
    fig.suptitle("Service interaction timing")
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return {"weekday_counts_utc": {weekdays[index]: day_counts[index] for index in range(7)},
            "hour_counts_utc": {str(index): hour_counts[index] for index in range(24)}}


def save_issue_chart(issue_labels: list[dict[str, str]], complaints: list[dict[str, str]],
                     resolutions: list[dict[str, str]], taxonomy: IssueTaxonomy,
                     output: Path) -> dict[str, Any]:
    sources = {"Label examples": issue_labels, "Complaints": complaints, "Resolutions": resolutions}
    mapped: dict[str, Counter[str]] = {}
    for source_name, rows in sources.items():
        counts: Counter[str] = Counter()
        for row in rows:
            label = row.get("issue_label", "")
            result = taxonomy.map_label(label)
            category = result["canonical_issue_label"] if result["mapping_status"] == "mapped" else f"Unmapped ({result['unmapped_reason']})"
            counts[category] += 1
        mapped[source_name] = counts
    categories = sorted({key for counts in mapped.values() for key in counts})
    x = list(range(len(categories)))
    width = 0.8 / max(1, len(sources))
    fig, ax = plt.subplots(figsize=(11, 5), constrained_layout=True)
    colors = ["#2563eb", "#f59e0b", "#10b981"]
    for source_index, (source_name, counts) in enumerate(mapped.items()):
        offsets = [index - 0.4 + width / 2 + source_index * width for index in x]
        ax.bar(offsets, [counts[category] for category in categories], width,
               label=source_name, color=colors[source_index])
    ax.set_xticks(x, categories, rotation=25, ha="right")
    ax.set_ylabel("Records")
    ax.set_title("Governed issue mix by source (counts, not deduplicated cases)")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return {source: dict(counts) for source, counts in mapped.items()}


def save_operational_chart(services: list[dict[str, str]], resolutions: list[dict[str, str]],
                           output: Path) -> dict[str, Any]:
    by_case: dict[str, datetime] = {}
    status_counts = Counter()
    for row in services:
        case_id = row.get("case_id", "").strip()
        if case_id:
            timestamp = parse_time(row["event_at"])
            by_case[case_id] = min(timestamp, by_case.get(case_id, timestamp))
        status_counts[row.get("status_code", "unknown").strip().casefold() or "unknown"] += 1
    lags = []
    for row in resolutions:
        case_id = row.get("case_id", "").strip()
        if case_id in by_case:
            hours = (parse_time(row["resolved_at"]) - by_case[case_id]).total_seconds() / 3600
            if hours >= 0:
                lags.append((case_id, hours))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), constrained_layout=True)
    if lags:
        labels = [f"Case {index}" for index in range(1, len(lags) + 1)]
        axes[0].bar(labels, [value for _, value in lags], color="#be123c")
        axes[0].set_ylabel("Hours")
    else:
        axes[0].text(0.5, 0.5, "No resolvable case links", ha="center", va="center", transform=axes[0].transAxes)
    axes[0].set_title("Observed event-to-resolution lag")
    statuses = sorted(status_counts)
    axes[1].bar(statuses, [status_counts[key] for key in statuses], color="#0891b2")
    axes[1].set(title="Service status mix", ylabel="Interactions")
    axes[1].tick_params(axis="x", rotation=20)
    for ax in axes:
        ax.grid(axis="y", alpha=0.25)
    fig.suptitle("Operational diagnostics (descriptive only)")
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return {"status_counts": dict(status_counts), "event_to_resolution_lag_hours": [value for _, value in lags],
            "event_to_resolution_lag_case_refs": [f"Case {index}" for index in range(1, len(lags) + 1)]}


def generate(fixtures_dir: Path, output_dir: Path, taxonomy_path: Path) -> dict[str, Any]:
    tables = {
        "Survey": read_csv(fixtures_dir / "survey_responses.csv"),
        "Service": read_csv(fixtures_dir / "service_events.csv"),
        "Complaints": read_csv(fixtures_dir / "complaints.csv"),
        "Orders": read_csv(fixtures_dir / "orders.csv"),
        "Resolutions": read_csv(fixtures_dir / "resolutions.csv"),
    }
    tables["Issue label examples"] = read_csv(fixtures_dir / "issue_labels.csv")
    labels = tables["Issue label examples"]
    taxonomy = IssueTaxonomy.from_file(taxonomy_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    scores = save_score_chart(tables["Survey"], output_dir / "score_distributions.png")
    missingness = save_missingness_chart(tables, output_dir / "missingness.png")
    channels = save_channel_chart(tables["Service"], tables["Orders"],
                                  {"phone": "voice", "call": "voice", "voice": "voice", "email": "email",
                                   "e-mail": "email", "chat": "chat", "messaging": "chat", "web": "web",
                                   "web form": "web", "social": "social"},
                                  output_dir / "channel_segments.png")
    timing = save_timing_chart(tables["Service"], output_dir / "contact_timing.png")
    issues = save_issue_chart(labels, tables["Complaints"], tables["Resolutions"], taxonomy,
                              output_dir / "issue_mix.png")
    operations = save_operational_chart(tables["Service"], tables["Resolutions"],
                                        output_dir / "operational_drivers.png")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary = {
        "generated_at_utc": now,
        "data_scope": "checked-in synthetic fixtures only",
        "row_counts": {name.lower(): len(rows) for name, rows in tables.items()},
        "scores": scores, "missingness": missingness, "channel_counts": channels,
        "contact_timing": timing, "issue_mix": issues, "operational_diagnostics": operations,
        "limitations": [
            "The fixtures are tiny, synthetic examples and are not representative of customers or operations.",
            "There is no product identifier or product segment in the sample, so product-segment analysis is unavailable.",
            "Survey records have no channel field and include an ambiguous customer/time linkage; score differences cannot be attributed to service interactions.",
            "The interaction fixture lacks case-created timestamps; plotted event-to-resolution lag is a proxy from the earliest observed interaction, not the official resolution-time KPI.",
            "Issue source counts overlap across examples, complaints, and resolutions and are not deduplicated case counts.",
            "All timestamps are converted to UTC for timing charts; actual operational analysis should use approved local/business calendars.",
        ],
    }
    (output_dir / "eda_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = [
        "# CXSignal EDA and service diagnostics", "",
        f"**Generated:** {now}  ", "**Scope:** checked-in synthetic fixtures only", "",
        "## Findings", "",
        f"- Survey sample: {len(tables['Survey'])} response rows. NPS sample has {scores.get('nps', {}).get('valid_responses', 0)} scores and observed NPS {scores.get('nps', {}).get('nps_points', 0):.1f}; CSAT sample has {scores.get('csat', {}).get('valid_responses', 0)} score(s). These values are descriptive only.",
        f"- Service sample: {len(tables['Service'])} interactions across {len(channels['service_interactions'])} normalized channel labels; {len(tables['Orders'])} orders across {len(channels['orders'])} order-channel labels.",
        f"- Issue taxonomy: {sum(issues['Label examples'].values())} source issue-label examples, including {sum(count for key, count in issues['Label examples'].items() if key.startswith('Unmapped'))} blank or unmapped labels. Complaint and resolution categories are shown separately because source rows may refer to the same case.",
        f"- Observed event-to-resolution lag proxy: {', '.join(f'{value:.1f}h' for value in operations['event_to_resolution_lag_hours']) or 'not available'}. This is not the official case resolution-time measure.",
        "- Product-level segmentation is unavailable because the sample has no product field. Survey channel attribution is also unavailable.", "",
        "## Charts", "",
        "![Survey score distributions](score_distributions.png)", "",
        "![Field missingness](missingness.png)", "",
        "![Channel segments](channel_segments.png)", "",
        "![Contact timing](contact_timing.png)", "",
        "![Issue mix](issue_mix.png)", "",
        "![Operational diagnostics](operational_drivers.png)", "",
        "## Interpretation limits", "",
    ]
    markdown.extend(f"- {limitation}" for limitation in summary["limitations"])
    markdown.append("")
    (output_dir / "eda_summary.md").write_text("\n".join(markdown), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate EDA charts for CXSignal source fixtures")
    parser.add_argument("--fixtures-dir", type=Path, default=Path("examples/fixtures"))
    parser.add_argument("--taxonomy", type=Path, default=Path("configs/taxonomy/issue_taxonomy.v1.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/eda-example"))
    args = parser.parse_args(argv)
    try:
        summary = generate(args.fixtures_dir, args.output_dir, args.taxonomy)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Generated EDA artifacts in {args.output_dir}; scope: {summary['data_scope']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
