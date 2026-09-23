"""Run: python -m unittest discover -s ui/tests -v."""

from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

UI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(UI_DIR))

from streamlit.testing.v1 import AppTest
from mock_data import search_contractors
from catalog import demo_catalog
from service import SearchService


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_file(str(UI_DIR / "app.py"), default_timeout=20).run()
        self.app.date_input(key="date").set_value(date(2026, 10, 11))

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
        self.app.selectbox(key="city").set_value("Зарубежье")
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
            "city": "Астана", "category": "Ведущий", "event_type": "свадьба",
            "date": "2026-10-10", "budget": 200000, "language": None, "hours": None,
        }
        self.assertEqual(search_contractors(request)["matches"], [])
        request["date"] = "2026-10-11"
        result = search_contractors(request)
        self.assertEqual(len(result["matches"]), 3)
        self.assertEqual(result["more_available"], 1)
        self.assertTrue(all(m["profile"]["synthetic"] for m in result["matches"]))

    def test_failure_clears_previous_cards_and_retry_recovers(self):
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.metric), 3)
        def fail(request):
            raise TimeoutError("SECRET_INTERNAL_DETAILS")
        failed_service = SearchService(fail, demo_catalog())
        with patch("service.get_search_service", return_value=failed_service):
            self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.metric), 0)
        self.assertNotIn("last_request", self.app.session_state)
        self.assertIn("временно недоступен", self.app.error[0].value)
        self.assertNotIn("SECRET", self.app.error[0].value)
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.metric), 3)
        self.assertEqual(len(self.app.error), 0)

    def test_malformed_backend_response_has_clear_error(self):
        invalid_service = SearchService(lambda request: {"matches": None}, demo_catalog())
        with patch("service.get_search_service", return_value=invalid_service):
            self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.metric), 0)
        self.assertIn("некорректный результат", self.app.error[0].value)

    def test_canonical_language_hours_and_partial_results(self):
        self.app.selectbox(key="language").set_value("казахский")
        self.app.number_input(key="hours").set_value(6)
        self.app.number_input(key="budget").set_value(80000)
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.metric), 1)
        request = self.app.session_state["last_request"]
        self.assertEqual(request["language"], "казахский")
        self.assertEqual(request["event_type"], "свадьба")
        self.assertEqual(request["hours"], 6)
        self.assertTrue(any("цена выше бюджета" in text.value for text in self.app.markdown))

    def test_non_demo_provenance_and_imputed_warnings(self):
        def provider(request):
            response = search_contractors(request)
            response["matches"][0]["profile"]["price_imputed"] = True
            response["matches"][0]["profile"]["city_imputed"] = True
            return response
        with patch("service.get_search_service", return_value=SearchService(provider, demo_catalog())):
            self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        captions = [item.value for item in self.app.caption]
        self.assertIn("СИНТЕТИЧЕСКИЙ ПРОФИЛЬ", captions)
        self.assertNotIn("ТЕСТОВЫЙ ПРОФИЛЬ", captions)
        self.assertTrue(any("Цена восстановлена" in value for value in captions))
        self.assertTrue(any("Город восстановлен" in value for value in captions))

    def test_empty_catalog_has_no_submit_and_no_exception(self):
        empty = SearchService(lambda request: None, {"city": (), "category": (), "event_type": ()})
        with patch("service.get_search_service", return_value=empty):
            self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.button), 0)
        self.assertIn("Каталог пока пуст", self.app.warning[0].value)


if __name__ == "__main__":
    unittest.main()
