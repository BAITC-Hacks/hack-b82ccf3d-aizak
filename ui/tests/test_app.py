"""Run: python -m unittest discover -s ui/tests -v."""

from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

UI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI_DIR))

from streamlit.testing.v1 import AppTest
from mock_data import search_contractors


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_file(str(UI_DIR / "app.py"), default_timeout=20).run()

    def test_initial_form_and_three_cards_after_submit(self):
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.title[0].value, "AIZAK")
        self.assertNotIn("result", self.app.session_state)
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.metric), 3)
        self.assertTrue(all("₸" in item.value for item in self.app.metric))
        self.assertTrue(all(m["match_reasons"] for m in self.app.session_state["result"]["matches"]))

    def test_budget_empty_and_recovery(self):
        self.app.number_input(key="budget").set_value(1)
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.metric), 0)
        self.assertIn("Подходящих подрядчиков нет", self.app.warning[0].value)
        self.app.number_input(key="budget").set_value(200000)
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.metric), 3)

    def test_city_and_category_are_applied(self):
        self.app.selectbox(key="city").set_value("Алматы")
        self.app.selectbox(key="category").set_value("Фотограф")
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.metric), 1)
        self.assertEqual(self.app.session_state["result"]["matches"][0]["id"], "demo-005")

    def test_no_category_and_optional_hours(self):
        self.app.selectbox(key="city").set_value("Шымкент")
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["result"]["status"], "no_category")
        self.app.selectbox(key="city").set_value("Астана")
        self.app.number_input(key="hours").set_value(12)
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["result"]["matches"], [])

    def test_demo_date_and_contract(self):
        request = {
            "city": "Астана", "category": "Ведущий", "event_type": "Свадьба",
            "date": "2030-01-15", "budget": 200000, "language": None, "hours": None,
        }
        self.assertEqual(search_contractors(request)["matches"], [])
        request["date"] = (date.today() + timedelta(days=2)).isoformat()
        if request["date"] == "2030-01-15":
            request["date"] = "2030-01-16"
        result = search_contractors(request)
        self.assertEqual(len(result["matches"]), 3)
        self.assertEqual(result["more_available"], 1)
        self.assertTrue(all(m["profile"]["synthetic"] for m in result["matches"]))


if __name__ == "__main__":
    unittest.main()
