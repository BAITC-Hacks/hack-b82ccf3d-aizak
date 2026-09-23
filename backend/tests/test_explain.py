"""Объяснения: соответствие исходным данным, неизменность фильтрации/сортировки, работа без AI."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import find_contractors, load_profiles  # noqa: E402
from backend.explain import description_highlights  # noqa: E402

DENSE = {"city": "Алматы", "date": "2026-10-15", "event_type": "свадьба", "category": "Ведущий", "budget": 1500000}
GENERIC = ("отличный выбор", "идеальный выбор", "лучший выбор", "для вашего мероприятия")


def _norm(s):
    return " ".join(s.split())


class ExplainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_profiles()
        cls.by_id = {p["id"]: p for p in cls.profiles}
        cls.queries = [DENSE, {**DENSE, "category": "Фотограф"}, {**DENSE, "category": "Банкетный зал"},
                       {**DENSE, "category": "Флорист", "budget": 500000},
                       {**DENSE, "event_type": "корпоратив", "language": "английский", "hours": 5}]

    def test_facts_match_source_profile(self):
        for q in self.queries:
            for m in find_contractors(q, self.profiles)["matches"]:
                p, f = self.by_id[m["id"]], m["facts"]
                self.assertEqual(f["price"]["from_kzt"], p["price_from_kzt"])
                self.assertEqual(f["event_format"]["accepted"], p["event_formats"])
                self.assertIn(q["event_type"], f["event_format"]["accepted"])
                self.assertEqual(f["languages"]["all"], p["languages"])
                self.assertEqual(f["hours"]["max_hours"], p["max_hours"])
                self.assertEqual(f["provenance"]["synthetic"], p["synthetic"])
                desc = _norm(p["description"])
                for h in f["description_highlights"]:  # только дословные фрагменты описания
                    self.assertIn(h.rstrip("…"), desc)

    def test_explanations_distinct_and_specific(self):
        for q in self.queries:
            matches = find_contractors(q, self.profiles)["matches"]
            texts = [m["explanation"] for m in matches]
            self.assertEqual(len(texts), len(set(texts)), q)
            for m in matches:
                self.assertNotIn(m["profile"]["anon_name"], m["explanation"])
                self.assertFalse(any(g in m["explanation"].lower() for g in GENERIC))
                self.assertIn(f"{m['profile']['price_from_kzt']:,}".replace(",", " "), m["explanation"])

    def test_distinctive_facts_are_true(self):
        m = find_contractors(DENSE, self.profiles)["matches"]
        prices = sorted(x["profile"]["price_from_kzt"] for x in m)
        for x in m:  # «самый низкий старт» — только при строго минимальной цене
            flagged = any("самый низкий старт" in d for d in x["facts"]["distinctive"])
            self.assertEqual(flagged, x["profile"]["price_from_kzt"] == prices[0] < prices[1])
        for x in m:
            others = [o for o in m if o is not x]
            for d in x["facts"]["distinctive"]:
                if d.startswith("единственный из подобранных работает на языке"):
                    lang = d.split(": ")[1]
                    self.assertIn(lang, x["profile"]["languages"])
                    self.assertTrue(all(lang not in o["profile"]["languages"] for o in others))

    def test_highlights_empty_when_nothing_relevant(self):
        self.assertEqual(description_highlights("Приветствую всех, дорогие друзья и гости", "свадьба"), [])
        self.assertEqual(description_highlights("Опыт ведения свадеб 13 лет", "свадьба"), ["Опыт ведения свадеб 13 лет"])

    def test_works_without_ai(self):
        for m in find_contractors(DENSE, self.profiles)["matches"]:
            self.assertEqual(m["explanation_source"], "template")
            self.assertTrue(m["explanation"].strip())

    def test_ai_hook_used_and_fallback_keeps_order(self):
        base = find_contractors(DENSE, self.profiles)
        ids = [m["id"] for m in base["matches"]]

        ai = find_contractors(DENSE, self.profiles, explainer=lambda f: f"AI: {f['id']}")
        self.assertEqual([m["id"] for m in ai["matches"]], ids)
        self.assertTrue(all(m["explanation_source"] == "ai" for m in ai["matches"]))

        def broken(_):
            raise TimeoutError("api down")
        for bad in (broken, lambda f: "", lambda f: None):
            res = find_contractors(DENSE, self.profiles, explainer=bad)
            self.assertEqual([m["id"] for m in res["matches"]], ids)
            self.assertEqual([m["explanation"] for m in res["matches"]], [m["explanation"] for m in base["matches"]])
            self.assertEqual(res["excluded"], base["excluded"])


if __name__ == "__main__":
    unittest.main()
