"""Release regressions for facts and optional ranking-provider failures."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import find_contractors, load_profiles
from backend.explain import build_facts

BASE = {"city": "Алматы", "category": "Ведущий", "date": "2026-10-15",
        "event_type": "свадьба", "budget": 1500000, "hours": None, "language": None}


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_profiles(Path(__file__).resolve().parents[2] / "data/hackathon-dataset-anonymized.csv")

    def test_malformed_semantic_provider_does_not_break_matching(self):
        original = find_contractors(BASE, self.profiles)
        for invalid in ([], "invalid", {"HK-42352": "invalid"}, {"HK-42352": float("nan")},
                        {"HK-42352": float("inf")}, {"HK-42352": None}, lambda request: []):
            with self.subTest(kind=type(invalid).__name__):
                self.assertEqual(find_contractors(BASE, self.profiles, similarity=invalid), original)

    def test_no_false_claim_about_all_peers_having_hour_limits(self):
        selected = [deepcopy(m["profile"]) for m in find_contractors(BASE, self.profiles)["matches"]]
        selected[0]["max_hours"] = selected[1]["max_hours"] = None
        selected[2]["max_hours"] = 8
        facts = build_facts(selected[0], BASE, selected[1:])
        self.assertFalse(any("в отличие от остальных" in item for item in facts["distinctive"]))

    def test_real_suggestions_have_reproducible_candidate_counts(self):
        for change in ({"date": "2026-10-10"}, {"date": "2026-12-26"}, {"budget": 1},
                       {"city": "Астана", "category": "Декоратор"}):
            request = {**BASE, **change}
            result = find_contractors(request, self.profiles)
            for suggestion in result["suggestions"]:
                alternative = {**request, suggestion["type"]: suggestion["value"]}
                changed = find_contractors(alternative, self.profiles)
                if suggestion["type"] == "city":
                    self.assertNotEqual(changed["status"], "no_category")
                else:
                    self.assertEqual(changed["funnel"]["passed"], suggestion["available"])
                    self.assertGreater(changed["funnel"]["passed"], result["funnel"]["passed"])

    def test_ranking_ties_and_real_order_are_reproducible(self):
        result = find_contractors(BASE, self.profiles)
        self.assertEqual(result, find_contractors(BASE, list(reversed(self.profiles))))
        self.assertEqual([m["id"] for m in result["matches"]], ["HK-42352", "HK-35215", "HK-27222"])
        ordering = [(-m["facts"]["ranking"]["score"], m["profile"]["price_from_kzt"], m["id"])
                    for m in result["matches"]]
        self.assertEqual(ordering, sorted(ordering))
