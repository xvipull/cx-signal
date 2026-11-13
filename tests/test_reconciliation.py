import unittest

from cx_signal.reconciliation import audit_linkage


def sample_data():
    surveys = [{"survey_response_id": f"survey-{number}"} for number in range(1, 5)]
    services = [{"service_event_id": f"service-{number}"} for number in range(1, 6)]
    matches = [
        {"survey_response_id": "survey-1", "service_event_id": "service-1"},
        {"survey_response_id": "survey-3", "service_event_id": "service-3"},
    ]
    quarantines = [
        {"survey_response_id": "survey-2", "quarantine_reason": "multiple_customer_time_window_matches",
         "candidate_service_event_ids": '["service-2", "service-4"]'},
        {"survey_response_id": "survey-4", "quarantine_reason": "no_eligible_service_match",
         "candidate_service_event_ids": "[]"},
    ]
    return surveys, services, matches, quarantines


def boundary_thresholds():
    return {
        "min_survey_match_rate": 0.50,
        "max_unmatched_survey_rate": 0.25,
        "max_survey_ambiguous_rate": 0.25,
        "min_service_match_rate": 0.40,
        "max_unmatched_service_rate": 0.20,
        "max_service_ambiguous_rate": 0.40,
    }


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.data = sample_data()

    def test_audit_classifies_matched_unmatched_and_ambiguous_records(self):
        audit, summary = audit_linkage(*self.data, boundary_thresholds())
        self.assertEqual(summary["counts"]["survey"], {"total": 4, "matched": 2, "unmatched": 1, "ambiguous": 1})
        self.assertEqual(summary["counts"]["service"], {"total": 5, "matched": 2, "unmatched": 1, "ambiguous": 2})
        self.assertEqual(summary["overall_status"], "pass")
        survey_ambiguous = next(row for row in audit if row["record_type"] == "survey" and row["disposition"] == "ambiguous")
        self.assertIn("service_", survey_ambiguous["ambiguous_candidate_refs"])

    def test_threshold_boundaries_are_inclusive(self):
        _, summary = audit_linkage(*self.data, boundary_thresholds())
        self.assertEqual(summary["overall_status"], "pass")
        self.assertTrue(all(check["status"] == "pass" for check in summary["threshold_checks"].values()))

    def test_match_rate_below_minimum_fails(self):
        thresholds = boundary_thresholds()
        thresholds["min_survey_match_rate"] = 0.51
        _, summary = audit_linkage(*self.data, thresholds)
        self.assertEqual(summary["threshold_checks"]["survey_match_rate"]["status"], "fail")
        self.assertEqual(summary["overall_status"], "fail")

    def test_ambiguity_above_maximum_fails(self):
        thresholds = boundary_thresholds()
        thresholds["max_service_ambiguous_rate"] = 0.39
        _, summary = audit_linkage(*self.data, thresholds)
        self.assertEqual(summary["threshold_checks"]["service_ambiguous_rate"]["status"], "fail")
        self.assertEqual(summary["overall_status"], "fail")


if __name__ == "__main__":
    unittest.main()
