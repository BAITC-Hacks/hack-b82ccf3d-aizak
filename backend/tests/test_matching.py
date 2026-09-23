import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loader import load_profiles, normalize_profile  # noqa: E402
from matching import find_contractors  # noqa: E402


def make(pid, **kw):
    raw = {
        "id": pid, "anon_name": f"Имя {pid}", "categories": "Фотограф", "city": "Алматы",
        "price_from_kzt": "300000", "event_formats": "свадьба|той", "languages": "русский|казахский",
        "max_hours": "8", "busy_dates": "2026-11-14", "synthetic": "False",
    }
    raw.update(kw)
    return normalize_profile(raw)


REQ = {"city": "Алматы", "date": "2026-11-15", "event_type": "свадьба",
       "category": "Фотограф", "budget": 500000}


class LoaderTest(unittest.TestCase):
    def test_real_dataset_loads(self):
        profiles = load_profiles()
        self.assertEqual(len(profiles), 66)
        p = profiles[0]
        self.assertIsInstance(p["categories"], list)
        self.assertIsInstance(p["busy_dates"], list)
        self.assertIsInstance(p["price_from_kzt"], int)
        self.assertEqual(sum(p["synthetic"] for p in profiles), 13)

    def test_missing_required_field_rejected(self):
        with self.assertRaises(ValueError):
            normalize_profile({"id": "X", "anon_name": "X"})


class MatchingTest(unittest.TestCase):
    def test_selects_and_sorts_by_price_then_id(self):
        profiles = [make("B", price_from_kzt="200000"), make("A", price_from_kzt="200000"),
                    make("C", price_from_kzt="100000"), make("D", price_from_kzt="400000")]
        res = find_contractors(REQ, profiles)
        self.assertEqual(res["status"], "found")
        self.assertEqual([m["id"] for m in res["matches"]], ["C", "A", "B"])
        self.assertEqual(res["more_available"], 1)
        self.assertEqual(res, find_contractors(REQ, list(reversed(profiles))))  # детерминизм

    def test_excludes_busy_over_budget_and_wrong_format(self):
        profiles = [make("OK"), make("BUSY", busy_dates="2026-11-15"),
                    make("EXP", price_from_kzt="900000"), make("FMT", event_formats="конференция"),
                    make("AST", city="Астана")]
        res = find_contractors(REQ, profiles)
        self.assertEqual([m["id"] for m in res["matches"]], ["OK"])
        reasons = {e["id"]: e["reasons"] for e in res["excluded"]}
        self.assertEqual(reasons, {"BUSY": ["busy_date"], "EXP": ["over_budget"], "FMT": ["format_mismatch"]})
        self.assertIn("1 из 3", res["message"])

    def test_three_outcomes_distinguishable(self):
        profiles = [make("P", busy_dates="2026-11-15")]
        self.assertEqual(find_contractors(REQ, profiles)["status"], "none_match")
        self.assertEqual(find_contractors({**REQ, "category": "Флорист"}, profiles)["status"], "no_category")

    def test_real_dataset_date_changes_result(self):
        profiles = load_profiles()
        base = {"city": "Алматы", "event_type": "свадьба", "category": "Ведущий", "budget": 10**8}
        a = find_contractors({**base, "date": "2026-10-10"}, profiles)
        b = find_contractors({**base, "date": "2026-12-26"}, profiles)
        self.assertNotEqual([m["id"] for m in a["matches"]], [m["id"] for m in b["matches"]])


if __name__ == "__main__":
    unittest.main()
