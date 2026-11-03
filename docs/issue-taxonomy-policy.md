# Governed issue taxonomy cleaning

**Taxonomy:** `cx-issues-v1`  
**Configuration:** `configs/taxonomy/issue_taxonomy.v1.json`  
**Status:** Starter hierarchy; Support, Product, and Operations owners must review before production use

The taxonomy maps issue labels from support, complaint, and service sources into a governed three-level hierarchy. It preserves the source label and records the normalized label, taxonomy version, mapping status, confidence, and reason whenever no mapping is produced.

## Mapping behavior

- Normalize lookup text with Unicode NFKC, case folding, and punctuation/whitespace tokenization. This normalized value is used only for deterministic alias lookup; the original source label is retained unchanged as `original_issue_label`.
- An exact canonical label match receives confidence `1.0`; a configured alias receives the policy's rule confidence (`0.95` in v1). These are fixed mapping-rule confidence scores, not probabilities, model scores, or measures of root-cause certainty.
- A unique configured label maps to `issue_code`, `issue_level_1`, `issue_level_2`, `issue_level_3`, and `canonical_issue_label` with `mapping_status=mapped` and an empty `unmapped_reason`.
- A blank label remains unmapped with confidence `0.0` and reason `blank_label`.
- An unknown label remains unmapped with confidence `0.0` and reason `no_governed_mapping`.
- If one normalized alias points to more than one issue code, it remains unmapped with confidence `0.0` and reason `ambiguous_alias`. The tool never chooses a category based on fuzzy similarity.
- Preserve every original row and its other fields in the derived output. The tool does not modify the source file.

## Ownership and change control

Support Operations owns contact and complaint label semantics. Product owns product-area issue distinctions, and Operations owns service and fulfillment classifications. CX Head resolves cross-functional category boundaries. The analytics steward maintains the versioned alias map and reports unmapped volume. Data Governance reviews any sensitive-field use.

For a new or changed mapping, record the source term, intended category, approving domain owner, effective date, and rationale in the project decision log or approved catalog. Add aliases without removing original labels from lineage. If a category boundary changes, create a new taxonomy version and document how historical reporting is handled; do not silently recode prior published metrics. Review unmapped and ambiguous labels on a regular cadence with the domain owners.

## Use

```sh
PYTHONPATH=src python3 -m cx_signal.taxonomy \
  --input examples/fixtures/issue_labels.csv \
  --output /tmp/cxsignal-issue-labels-staged.csv \
  --taxonomy configs/taxonomy/issue_taxonomy.v1.json \
  --label-column issue_label
```

The output includes `original_issue_label`, `normalized_issue_label`, taxonomy hierarchy fields, `mapping_confidence`, `mapping_status`, and `unmapped_reason`. Write derived outputs to a controlled location when processing real data. Do not commit customer records or sensitive free text to this public repository.
