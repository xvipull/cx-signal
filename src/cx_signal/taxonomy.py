"""Governed normalization of free-text issue labels."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


class TaxonomyError(Exception):
    """Raised when a taxonomy or input file is invalid."""


def normalize_label(value: str | None) -> str:
    """Normalize text for deterministic alias lookup, without changing source text."""
    text = unicodedata.normalize("NFKC", value or "").casefold()
    tokens = re.findall(r"[\w]+", text, flags=re.UNICODE)
    return " ".join(tokens)


class IssueTaxonomy:
    def __init__(self, definition: dict[str, Any]):
        self.version = definition.get("taxonomy_version")
        if not self.version:
            raise TaxonomyError("Taxonomy must define taxonomy_version")
        confidence = float(definition.get("alias_confidence", 0.95))
        if not 0 <= confidence <= 1:
            raise TaxonomyError("alias_confidence must be between 0 and 1")
        self.alias_confidence = confidence
        self.lookup: dict[str, list[tuple[dict[str, Any], float]]] = defaultdict(list)
        categories = definition.get("categories")
        if not isinstance(categories, list) or not categories:
            raise TaxonomyError("Taxonomy must include a non-empty categories list")
        seen_codes: set[str] = set()
        for category in categories:
            code = category.get("issue_code")
            if not code or code in seen_codes:
                raise TaxonomyError(f"Missing or duplicate issue_code: {code}")
            seen_codes.add(code)
            for field in ("level_1", "level_2", "level_3", "canonical_label"):
                if not category.get(field):
                    raise TaxonomyError(f"Category {code} is missing {field}")
            labels = [(category["canonical_label"], 1.0)]
            labels.extend((alias, self.alias_confidence) for alias in category.get("aliases", []))
            for label, score in labels:
                key = normalize_label(label)
                if key:
                    self.lookup[key].append((category, score))

    @classmethod
    def from_file(cls, path: Path) -> "IssueTaxonomy":
        try:
            definition = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TaxonomyError(f"Cannot load taxonomy {path}: {exc}") from exc
        if not isinstance(definition, dict):
            raise TaxonomyError("Taxonomy JSON root must be an object")
        return cls(definition)

    def map_label(self, original_label: str | None) -> dict[str, Any]:
        original = original_label or ""
        normalized = normalize_label(original)
        result: dict[str, Any] = {
            "original_issue_label": original,
            "normalized_issue_label": normalized,
            "taxonomy_version": self.version,
            "issue_code": "",
            "issue_level_1": "",
            "issue_level_2": "",
            "issue_level_3": "",
            "canonical_issue_label": "",
            "mapping_status": "unmapped",
            "mapping_confidence": 0.0,
            "unmapped_reason": "blank_label" if not normalized else "no_governed_mapping",
        }
        candidates = self.lookup.get(normalized, [])
        unique = {item[0]["issue_code"]: item for item in candidates}
        if len(unique) == 1:
            category, confidence = next(iter(unique.values()))
            result.update({
                "issue_code": category["issue_code"],
                "issue_level_1": category["level_1"],
                "issue_level_2": category["level_2"],
                "issue_level_3": category["level_3"],
                "canonical_issue_label": category["canonical_label"],
                "mapping_status": "mapped",
                "mapping_confidence": confidence,
                "unmapped_reason": "",
            })
        elif len(unique) > 1:
            result["unmapped_reason"] = "ambiguous_alias"
        return result


def clean_csv(input_path: Path, output_path: Path, taxonomy_path: Path, label_column: str) -> int:
    taxonomy = IssueTaxonomy.from_file(taxonomy_path)
    try:
        with input_path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames or label_column not in reader.fieldnames:
                raise TaxonomyError(f"Input must contain issue label column '{label_column}'")
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise TaxonomyError(f"Cannot read input {input_path}: {exc}") from exc
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_fields = list(taxonomy.map_label("").keys())
    with output_path.open("w", encoding="utf-8", newline="") as target:
        fields = [field for field in reader.fieldnames if field != label_column] + mapping_fields
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            mapped = taxonomy.map_label(row.get(label_column))
            writer.writerow({**{key: value for key, value in row.items() if key != label_column}, **mapped})
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Map free-text issue labels to a governed CX taxonomy")
    parser.add_argument("--input", type=Path, required=True, help="Derived CSV containing issue labels")
    parser.add_argument("--output", type=Path, required=True, help="New derived CSV path")
    parser.add_argument("--taxonomy", type=Path, required=True, help="Versioned taxonomy JSON")
    parser.add_argument("--label-column", default="issue_label", help="Source free-text label column")
    args = parser.parse_args(argv)
    try:
        count = clean_csv(args.input, args.output, args.taxonomy, args.label_column)
    except (TaxonomyError, OSError, ValueError) as exc:
        print(f"Taxonomy cleaning failed: {exc}", file=sys.stderr)
        return 2
    print(f"Mapped {count} issue labels to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
