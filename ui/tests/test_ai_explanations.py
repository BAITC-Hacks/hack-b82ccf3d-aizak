"""Real CSV -> matching -> mocked OpenAI -> actual Streamlit cards, no network."""
from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui"))
from backend.ai_config import AIConfig
from streamlit.testing.v1 import AppTest


class AIInterfaceTests(unittest.TestCase):
    def setUp(self):
        config = patch("backend.explanations.load_ai_config", return_value=AIConfig(api_key="test-only-dummy"))
        config.start()
        self.addCleanup(config.stop)
        guard = patch("backend.explanations.build_opener", side_effect=AssertionError("Network forbidden"))
        self.guard = guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self):
        self.guard.assert_not_called()

    def submit(self, app, budget=1500000):
        app.selectbox(key="city").set_value("Алматы")
        app.selectbox(key="category").set_value("Ведущий")
        app.selectbox(key="event_type").set_value("свадьба")
        app.date_input(key="date").set_value(date(2026, 10, 15))
        app.number_input(key="budget").set_value(budget)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)

    def test_ai_text_reaches_cards_once_and_does_not_change_ids(self):
        def respond(payload, config):
            candidates = json.loads(payload["input"])["candidates"]
            texts = [{"id": c["id"], "explanation": c["facts"]["anon_name"] +
                      ": выбранный формат есть в анкете. По календарю свободен на дату мероприятия."}
                     for c in reversed(candidates)]
            return {"status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps({"explanations": texts}, ensure_ascii=False)}]}]}
        with patch("backend.explanations._post_openai", side_effect=respond) as transport:
            app = AppTest.from_file(str(ROOT / "ui" / "app.py")).run()
            transport.assert_not_called()
            self.submit(app)
            result = app.session_state["result"]
            self.assertEqual(result["explanation_status"], "openai")
            self.assertEqual([m["id"] for m in result["matches"]], ["HK-44923", "HK-35215", "HK-42352"])
            for match in result["matches"]:
                self.assertIn(match["explanation"], [item.value for item in app.markdown])
            self.assertEqual([c.value for c in app.caption].count("Объяснение: OpenAI"), 3)
            app.run()  # Expander/widget reruns must not generate paid calls.
            transport.assert_called_once()

    def test_api_failure_renders_fallback_without_exposing_exception(self):
        with patch("backend.explanations._post_openai", side_effect=TimeoutError("private-dummy-token")) as transport:
            app = AppTest.from_file(str(ROOT / "ui" / "app.py")).run()
            self.submit(app)
            result = app.session_state["result"]
            self.assertEqual(result["explanation_status"], "api_unavailable")
            self.assertEqual(len(app.metric), 3)
            self.assertEqual([c.value for c in app.caption].count("Объяснение по данным каталога"), 3)
            self.assertNotIn("private-dummy-token", json.dumps(result))
            transport.assert_called_once()

    def test_no_matches_never_calls_openai(self):
        with patch("backend.explanations._post_openai") as transport:
            app = AppTest.from_file(str(ROOT / "ui" / "app.py")).run()
            self.submit(app, budget=1)
            self.assertEqual(app.session_state["result"]["status"], "none_match")
            self.assertEqual(len(app.metric), 0)
            transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
