"""Offline end-to-end checks against the unchanged official CSV, not demo profiles."""
from datetime import date
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui"))

from backend import find_contractors, load_profiles
from backend.loader import DEFAULT_DATASET
from contracts import BackendError
from service import get_search_service
from streamlit.testing.v1 import AppTest

REQUEST = {
    "city": "Алматы", "category": "Ведущий", "date": "2026-10-15",
    "event_type": "свадьба", "budget": 1500000, "hours": None, "language": None,
}
DENSE_IDS = ["HK-44923", "HK-35215", "HK-42352"]


class RealBackendTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"AIZAK_DATASET": str(DEFAULT_DATASET), "AIZAK_AI_ENABLED": "false"})
        environment.start()
        self.addCleanup(environment.stop)
        network = patch("backend.explanations._post_openai", side_effect=AssertionError("Network forbidden in tests"))
        self.network = network.start()
        self.addCleanup(network.stop)

    def tearDown(self):
        self.network.assert_not_called()

    def app(self):
        return AppTest.from_file(str(ROOT / "ui" / "app.py"), default_timeout=20).run()

    def submit(self, app, **changes):
        request = {**REQUEST, **changes}
        for key in ("city", "category", "event_type", "language"):
            app.selectbox(key=key).set_value(request[key])
        app.date_input(key="date").set_value(date.fromisoformat(request["date"]))
        app.number_input(key="budget").set_value(request["budget"])
        app.number_input(key="hours").set_value(request["hours"] or 0)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(dict(app.session_state["last_request"]), request)
        return app.session_state["result"]

    def test_factory_loads_official_profiles_without_mock_provider(self):
        self.assertEqual(len(load_profiles()), 66)
        with patch("mock_data.search_contractors", side_effect=AssertionError("mock used")):
            service = get_search_service()
            result = service.search(REQUEST)
        self.assertFalse(service.is_demo)
        self.assertEqual([m["id"] for m in result["matches"]], DENSE_IDS)
        self.assertEqual(service.calendar_start, date(2026, 9, 23))
        self.assertEqual(service.calendar_end, date(2026, 12, 31))

    def test_real_form_cards_and_request_contract(self):
        app = self.app()
        self.assertFalse(app.exception)
        self.assertFalse(app.info)
        result = self.submit(app)
        self.assertEqual(result["status"], "found")
        self.assertEqual([m["id"] for m in result["matches"]], DENSE_IDS)
        self.assertEqual(len(app.metric), 3)
        self.assertEqual(result["funnel"]["in_city_category"], 10)
        shown_names = [item.value for item in app.subheader]
        for match in result["matches"]:
            self.assertIn(match["profile"]["anon_name"], shown_names)
            self.assertIn(match["explanation"], [item.value for item in app.markdown])
        self.assertNotIn("ТЕСТОВЫЙ ПРОФИЛЬ", [item.value for item in app.caption])

    def test_real_rare_category_has_two_cards_and_provenance(self):
        app = self.app()
        result = self.submit(app, category="Флорист", budget=500000, hours=100)
        self.assertEqual([m["id"] for m in result["matches"]], ["HK-39372", "HK-90001"])
        self.assertEqual(len(app.metric), 2)
        self.assertIn("2 из 3", result["message"])
        self.assertTrue(all(m["profile"]["max_hours"] is None for m in result["matches"]))
        self.assertIn("СИНТЕТИЧЕСКИЙ ПРОФИЛЬ", [item.value for item in app.caption])

    def test_real_no_category_clears_previous_cards(self):
        app = self.app()
        self.submit(app)
        result = self.submit(app, city="Астана", category="Декоратор", budget=500000)
        self.assertEqual(result["status"], "no_category")
        self.assertEqual(result["funnel"]["in_city_category"], 0)
        self.assertEqual(len(app.metric), 0)
        self.assertIn("нет такой категории", app.warning[0].value)

    def test_real_none_match_has_busy_and_budget_reasons(self):
        app = self.app()
        result = self.submit(app, city="Астана", category="Банкетный зал",
                             date="2026-12-26", budget=300000)
        self.assertEqual(result["status"], "none_match")
        self.assertEqual(len(app.metric), 0)
        self.assertIn("busy_date", result["excluded"][0]["reasons"])
        self.assertIn("over_budget", result["excluded"][0]["reasons"])
        self.assertIn("категория есть", app.warning[0].value)

    def test_real_date_change_and_repeated_request(self):
        app = self.app()
        first = self.submit(app, date="2026-10-10")
        self.assertEqual([m["id"] for m in first["matches"]], ["HK-27222", "HK-77838"])
        second = self.submit(app, date="2026-12-26")
        self.assertEqual([m["id"] for m in second["matches"]], ["HK-44923"])
        excluded = {e["id"]: e["reasons"] for e in second["excluded"]}
        for match in first["matches"]:
            self.assertIn("busy_date", excluded[match["id"]])
        self.assertEqual(second, self.submit(app, date="2026-12-26"))

    def test_real_optional_language_hours_and_budget(self):
        app = self.app()
        result = self.submit(app, language="русский", hours=4, budget=1500000)
        self.assertEqual(result["status"], "found")
        for match in result["matches"]:
            profile = match["profile"]
            self.assertIn("русский", profile["languages"])
            self.assertGreaterEqual(profile["max_hours"], 4)
            self.assertLessEqual(profile["price_from_kzt"], 1500000)
            self.assertNotIn(REQUEST["date"], profile["busy_dates"])

    def test_real_order_does_not_depend_on_input_file_order(self):
        profiles = load_profiles()
        expected = get_search_service().search(REQUEST)
        expected.pop("explanation_status")
        for match in expected["matches"]:
            match.pop("explanation")
            match.pop("explanation_source")
        self.assertEqual(expected, find_contractors(REQUEST, list(reversed(profiles))))

    def test_missing_csv_has_clear_error_and_no_old_or_mock_cards(self):
        app = self.app()
        self.submit(app)
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"AIZAK_DATASET": str(Path(directory) / "missing.csv")}):
                with self.assertRaises(BackendError):
                    get_search_service()
                app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.metric), 0)
        self.assertNotIn("result", app.session_state)
        self.assertIn("Не удалось загрузить каталог", app.error[0].value)

    def test_default_csv_load_is_independent_of_working_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with patch.dict(os.environ, {"AIZAK_DATASET": ""}):
                    result = get_search_service().search(REQUEST)
            finally:
                os.chdir(previous)
        self.assertEqual([m["id"] for m in result["matches"]], DENSE_IDS)


if __name__ == "__main__":
    unittest.main()
