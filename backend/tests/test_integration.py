"""Интеграция: реальный датасет -> запрос -> подбор -> структурированный результат (импорт как из Streamlit)."""
import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend import find_contractors, load_profiles  # noqa: E402
from backend.loader import DEFAULT_DATASET  # noqa: E402

QUERIES = {
    "dense": ({"city": "Алматы", "date": "2026-10-15", "event_type": "свадьба",
               "category": "Ведущий", "budget": 1500000, "hours": None, "language": None}, "found"),
    "rare": ({"city": "Алматы", "date": "2026-10-15", "event_type": "свадьба",
              "category": "Флорист", "budget": 500000}, "found"),
    "empty": ({"city": "Астана", "date": "2026-12-26", "event_type": "свадьба",
               "category": "Банкетный зал", "budget": 300000}, "none_match"),
    "no_category": ({"city": "Астана", "date": "2026-10-15", "event_type": "свадьба",
                     "category": "Декоратор", "budget": 500000}, "no_category"),
}


class IntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_profiles()

    def assert_contract(self, res):
        self.assertEqual(set(res), {"status", "message", "matches", "excluded", "more_available", "funnel"})
        self.assertTrue(res["message"].strip())
        self.assertLessEqual(len(res["matches"]), 3)
        self.assertEqual(res["status"] == "found", bool(res["matches"]))
        ids = [m["id"] for m in res["matches"]] + [e["id"] for e in res["excluded"]]
        self.assertEqual(len(ids), len(set(ids)))
        prices = [(m["profile"]["price_from_kzt"], m["id"]) for m in res["matches"]]
        self.assertEqual(prices, sorted(prices))
        for m in res["matches"]:
            self.assertEqual(m["profile"]["id"], m["id"])
            self.assertTrue(m["match_reasons"] and all(isinstance(r, str) for r in m["match_reasons"]))
            self.assertIsInstance(m["warnings"], list)
            for f in ("synthetic", "price_imputed", "city_imputed"):
                self.assertIs(type(m["profile"][f]), bool)
        for e in res["excluded"]:
            self.assertTrue(e["reasons"])
        json.dumps(res, ensure_ascii=False)  # сериализуемо для session_state / логов

    def test_demo_queries_end_to_end(self):
        for name, (req, status) in QUERIES.items():
            with self.subTest(name):
                res = find_contractors(req, self.profiles)
                self.assert_contract(res)
                self.assertEqual(res["status"], status)
                self.assertEqual(res, find_contractors(req, self.profiles))

    def test_jsonl_gives_same_profiles_as_csv(self):
        with DEFAULT_DATASET.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            for f in ("categories", "event_formats", "languages", "busy_dates"):
                r[f] = [v for v in r[f].split("|") if v]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hackathon-dataset-anonymized.jsonl"
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            self.assertEqual(load_profiles(path), self.profiles)
            with patch.dict(os.environ, {"AIZAK_DATASET": str(path)}):
                self.assertEqual(load_profiles(), self.profiles)


if __name__ == "__main__":
    unittest.main()
