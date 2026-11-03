import json
import unittest
from pathlib import Path

from cx_signal.taxonomy import IssueTaxonomy


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = ROOT / "configs" / "taxonomy" / "issue_taxonomy.v1.json"


class IssueTaxonomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.taxonomy = IssueTaxonomy.from_file(TAXONOMY_PATH)

    def test_known_alias_maps_to_governed_hierarchy(self):
        result = self.taxonomy.map_label("Late delivery")
        self.assertEqual(result["issue_code"], "delivery_delay")
        self.assertEqual(result["issue_level_1"], "fulfillment")
        self.assertEqual(result["mapping_status"], "mapped")
        self.assertEqual(result["mapping_confidence"], 0.95)
        self.assertEqual(result["original_issue_label"], "Late delivery")

    def test_case_and_punctuation_are_normalized_but_original_is_preserved(self):
        result = self.taxonomy.map_label("ITEM ARRIVED BROKEN!")
        self.assertEqual(result["issue_code"], "delivery_damage")
        self.assertEqual(result["original_issue_label"], "ITEM ARRIVED BROKEN!")
        self.assertEqual(result["normalized_issue_label"], "item arrived broken")

    def test_unknown_and_blank_labels_are_explained(self):
        unknown = self.taxonomy.map_label("new issue type")
        blank = self.taxonomy.map_label("   ")
        self.assertEqual(unknown["unmapped_reason"], "no_governed_mapping")
        self.assertEqual(blank["unmapped_reason"], "blank_label")
        self.assertEqual(unknown["mapping_confidence"], 0.0)

    def test_conflicting_alias_is_quarantined_as_ambiguous(self):
        definition = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
        definition["categories"][1]["aliases"].append("late delivery")
        taxonomy = IssueTaxonomy(definition)
        result = taxonomy.map_label("Late delivery")
        self.assertEqual(result["mapping_status"], "unmapped")
        self.assertEqual(result["unmapped_reason"], "ambiguous_alias")


if __name__ == "__main__":
    unittest.main()
