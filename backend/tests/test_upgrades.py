"""Ранжирование, подсказки, трассировка, проверка AI-текста по фактам."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import find_contractors, load_profiles  # noqa: E402
from backend.grounding import check_explanation  # noqa: E402
from backend.loader import normalize_profile  # noqa: E402

REQ = {"city": "Алматы", "date": "2026-11-15", "event_type": "свадьба", "category": "Фотограф", "budget": 500000}
QUERIES = [
    {"city": "Алматы", "date": "2026-10-15", "event_type": "свадьба", "category": c, "budget": 1500000}
    for c in ("Ведущий", "Фотограф", "Банкетный зал", "Флорист")
]


def make(pid, **kw):
    raw = {"id": pid, "anon_name": f"Имя {pid}", "categories": "Фотограф", "city": "Алматы",
           "price_from_kzt": "300000", "event_formats": "свадьба|той", "languages": "русский",
           "max_hours": "8", "busy_dates": "", "description": ""}
    raw.update(kw)
    return normalize_profile(raw)


class RankingTest(unittest.TestCase):
    def test_wedding_specialist_outranks_slightly_cheaper(self):
        res = find_contractors(REQ, [make("CHEAP", price_from_kzt="300000"),
                                     make("SPEC", price_from_kzt="400000", description="Снимаю свадьбы 10 лет")])
        self.assertEqual([m["id"] for m in res["matches"]], ["SPEC", "CHEAP"])
        top = res["matches"][0]
        self.assertIn("описание прямо про этот формат", top["facts"]["ranking"]["above_next_because"])
        self.assertTrue(any(r.startswith("Место 1") for r in top["match_reasons"]))

    def test_semantic_similarity_component(self):
        profiles = [make("A"), make("B")]
        res = find_contractors(REQ, profiles, similarity={"B": 1.0})
        self.assertEqual([m["id"] for m in res["matches"]], ["B", "A"])
        res = find_contractors(REQ, profiles, similarity=lambda req: {"A": 0.9, "B": 0.1})
        self.assertEqual([m["id"] for m in res["matches"]], ["A", "B"])
        broken = find_contractors(REQ, profiles, similarity=lambda req: 1 / 0)
        self.assertEqual([m["id"] for m in broken["matches"]], ["A", "B"])


class SuggestionsTraceTest(unittest.TestCase):
    def test_date_and_budget_suggestions(self):
        profiles = [make("BUSY1", busy_dates="2026-11-15"), make("BUSY2", busy_dates="2026-11-15|2026-11-14"),
                    make("EXP", price_from_kzt="650000")]
        res = find_contractors(REQ, profiles)
        self.assertEqual(res["status"], "none_match")
        dates = [s for s in res["suggestions"] if s["type"] == "date"]
        self.assertEqual(dates[0], {"type": "date", "value": "2026-11-14", "available": 1, "text": "14.11.2026 подходят 1"})
        self.assertEqual(dates[1]["value"], "2026-11-16")
        self.assertEqual(dates[1]["available"], 2)
        budget = [s for s in res["suggestions"] if s["type"] == "budget"][0]
        self.assertEqual((budget["value"], budget["available"]), (650000, 1))
        self.assertIn("+150 000 ₸", budget["text"])

    def test_no_category_suggests_city(self):
        res = find_contractors({**REQ, "city": "Астана"}, [make("A")])
        self.assertEqual(res["suggestions"][0]["value"], "Алматы")

    def test_trace_is_sequential_funnel(self):
        profiles = [make("OK"), make("BUSY", busy_dates="2026-11-15"), make("EXP", price_from_kzt="900000"),
                    make("FMT", event_formats="конференция")]
        trace = find_contractors({**REQ, "language": "русский"}, profiles)["trace"]
        self.assertEqual([(t["stage"], t["remaining"]) for t in trace], [
            ("город и категория", 4), ("свободен на дату", 3), ("укладывается в бюджет", 2),
            ("берёт этот формат", 1), ("работает на нужном языке", 1), ("ранжирование, показано", 1)])


class GroundingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_profiles()

    def test_template_always_passes_check(self):
        for q in QUERIES:
            for m in find_contractors(q, self.profiles)["matches"]:
                self.assertEqual(check_explanation(m["explanation"], m["facts"]), [], m["explanation"])

    def test_invented_facts_rejected_and_replaced(self):
        base = find_contractors(QUERIES[0], self.profiles)
        facts = base["matches"][0]["facts"]
        self.assertTrue(check_explanation("Скидка 35% и 500 гостей.", facts))
        self.assertTrue(check_explanation("В описании: «работаем с 1990 года»", facts))
        self.assertTrue(check_explanation(f"{facts['name']} — отличный выбор", facts))

        liar = find_contractors(QUERIES[0], self.profiles, explainer=lambda f: "Скидка 35% только сегодня.")
        for m, b in zip(liar["matches"], base["matches"]):
            self.assertEqual(m["explanation_source"], "template_after_check")
            self.assertEqual(m["explanation"], b["explanation"])
            self.assertTrue(m["explanation_check"])

    def test_grounded_ai_text_accepted(self):
        def honest(f):
            return f"Старт от {f['price']['from_kzt']:,} ₸, запас {f['price']['margin_pct']}% бюджета.".replace(",", " ")
        res = find_contractors(QUERIES[0], self.profiles, explainer=honest)
        self.assertTrue(all(m["explanation_source"] == "ai" and not m["explanation_check"] for m in res["matches"]))


if __name__ == "__main__":
    unittest.main()
