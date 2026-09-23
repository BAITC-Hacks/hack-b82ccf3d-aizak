"""All AI tests use injected/mock transport and dummy keys, never the live API."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend import find_contractors, load_profiles
from backend.ai_config import AIConfig, load_ai_config
from backend.explain import explain_fallback
from backend.explanations import OPENAI_URL, _NoRedirect, _post_openai, add_explanations
from urllib.error import HTTPError

REQUEST = {"city": "Алматы", "category": "Ведущий", "date": "2026-10-15",
           "event_type": "свадьба", "budget": 1500000, "hours": None, "language": None}


def response_for(result):
    # Reverse API output deliberately: the UI must preserve the original ranking.
    items = [{"id": m["id"], "explanation": explain_fallback(m["facts"])}
             for m in reversed(result["matches"])]
    return envelope(items)


def envelope(items):
    return {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps({"explanations": items}, ensure_ascii=False)}]}]}


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / ".env"

    def test_absent_file_is_offline_and_repr_hides_key(self):
        config = load_ai_config(environ={}, env_file=self.path)
        self.assertTrue(config.valid)
        self.assertEqual(config.api_key, "")
        self.assertNotIn("dummy-private", repr(AIConfig(api_key="dummy-private")))

    def test_env_overrides_dotenv_without_modifying_process(self):
        self.path.write_text('# local\nexport OPENAI_API_KEY="file-dummy" # comment\n'
                             'OPENAI_MODEL=custom-model\nAIZAK_AI_TIMEOUT_SECONDS=2.5\n', encoding="utf-8-sig")
        before = dict(os.environ)
        config = load_ai_config(environ={"OPENAI_API_KEY": "env-dummy"}, env_file=self.path)
        self.assertEqual(config.api_key, "env-dummy")
        self.assertEqual(config.model, "custom-model")
        self.assertEqual(config.timeout, 2.5)
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(load_ai_config(environ={"OPENAI_API_KEY": ""}, env_file=self.path).api_key, "")

    def test_dotenv_is_resolved_from_explicit_path_not_cwd(self):
        self.path.write_text("OPENAI_API_KEY='file-dummy'\n", encoding="utf-8")
        previous = Path.cwd()
        try:
            os.chdir(self.path.parent)
            config = load_ai_config(environ={}, env_file=self.path)
        finally:
            os.chdir(previous)
        self.assertEqual(config.api_key, "file-dummy")

    def test_invalid_values_fail_closed(self):
        for setting in ("AIZAK_AI_TIMEOUT_SECONDS=NaN", "AIZAK_AI_TIMEOUT_SECONDS=999",
                        "AIZAK_AI_TIMEOUT_SECONDS=-1", "AIZAK_AI_ENABLED=maybe",
                        "OPENAI_API_KEY='unterminated"):
            with self.subTest(setting=setting):
                self.path.write_text(setting, encoding="utf-8")
                self.assertFalse(load_ai_config(environ={}, env_file=self.path).valid)


class ExplanationTests(unittest.TestCase):
    def setUp(self):
        self.profiles = load_profiles(ROOT / "data" / "hackathon-dataset-anonymized.csv")
        self.result = find_contractors(REQUEST, self.profiles)
        self.before = deepcopy(self.result)
        self.config = AIConfig(api_key="test-only-not-a-real-key")
        guard = patch("backend.explanations.build_opener", side_effect=AssertionError("Real network forbidden"))
        self.guard = guard.start()
        self.addCleanup(guard.stop)

    def assert_matching_unchanged(self, enriched):
        core = deepcopy(enriched)
        core.pop("explanation_status", None)
        expected = deepcopy(self.before)
        for result in (core, expected):
            for match in result["matches"]:
                match.pop("explanation", None)
                match.pop("explanation_source", None)
        self.assertEqual(core, expected)
        self.assertEqual(self.result, self.before)

    def test_ai_success_preserves_order_and_all_matching_fields(self):
        transport = Mock(return_value=response_for(self.result))
        result = add_explanations(REQUEST, self.result, config=self.config, transport=transport)
        self.assertEqual(result["explanation_status"], "openai")
        self.assert_matching_unchanged(result)
        self.assertTrue(all(m["explanation_source"] == "openai" for m in result["matches"]))
        self.assertEqual(len({m["explanation"] for m in result["matches"]}), 3)
        transport.assert_called_once()

    def test_payload_contains_only_selected_confirmed_facts(self):
        transport = Mock(return_value=response_for(self.result))
        add_explanations({**REQUEST, "private_note": "do-not-send"}, self.result,
                         config=self.config, transport=transport)
        payload = transport.call_args.args[0]
        data = json.loads(payload["input"])
        self.assertEqual([c["id"] for c in data["candidates"]], [m["id"] for m in self.result["matches"]])
        self.assertEqual(set(data), {"request", "candidates"})
        self.assertNotIn("private_note", data["request"])
        for candidate in data["candidates"]:
            self.assertNotIn("description", candidate["facts"])
            self.assertNotIn("busy_dates", candidate["facts"])
            self.assertNotIn("name", candidate["facts"])
            self.assertIn("price_imputed", candidate["facts"]["provenance"])
            self.assertIn("ranking", candidate["facts"])
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertNotIn(self.config.api_key, json.dumps(payload))

    def test_disabled_missing_key_and_bad_config_never_call_api(self):
        for config, status in ((AIConfig(), "missing_key"),
                               (AIConfig(api_key="dummy", enabled=False), "disabled"),
                               (AIConfig(valid=False), "configuration_error")):
            with self.subTest(status=status):
                transport = Mock()
                result = add_explanations(REQUEST, self.result, config=config, transport=transport)
                transport.assert_not_called()
                self.assertEqual(result["explanation_status"], status)
                self.assert_matching_unchanged(result)
                self.assertEqual(len({m["explanation"] for m in result["matches"]}), 3)
                for m in result["matches"]:
                    self.assertEqual(m["explanation"], explain_fallback(m["facts"]))
                    self.assertEqual(m["explanation_source"], "fallback")

    def test_timeout_auth_rate_limit_and_network_errors_fall_back_once(self):
        errors = [TimeoutError("private-key-must-not-leak"), OSError("private-key-must-not-leak"),
                  HTTPError(OPENAI_URL, 401, "private-key-must-not-leak", {}, None),
                  HTTPError(OPENAI_URL, 429, "private-key-must-not-leak", {}, None)]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                transport = Mock(side_effect=error)
                result = add_explanations(REQUEST, self.result, config=self.config, transport=transport)
                self.assertEqual(result["explanation_status"], "api_unavailable")
                self.assertNotIn("private-key", json.dumps(result))
                transport.assert_called_once()
                self.assert_matching_unchanged(result)

    def test_invalid_or_partial_responses_fall_back_for_all_cards(self):
        items = json.loads(response_for(self.result)["output"][0]["content"][0]["text"])["explanations"]
        invalid_items = [items[:-1], items + items[:1], [items[0]] * 3,
                         [{**items[0], "id": "unselected"}, *items[1:]],
                         [{**items[0], "explanation": ""}, *items[1:]],
                         [{**items[0], "explanation": "Скидка 987654% и опыт 1234567 лет гарантированы."}, *items[1:]],
                         [{**items[0], "explanation": "Из описания: «Невероятный неподтверждённый опыт»"}, *items[1:]],
                         [{**items[0], "explanation": items[0]["explanation"] + " https://bad.test"}, *items[1:]],
                         [{**items[0], "explanation": 123}, *items[1:]],
                         [{**items[0], "extra": "invented"}, *items[1:]]]
        malformed = [{}, {"status": "incomplete", "output": []},
                     {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]},
                     {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "not json"}]}]}]
        for response in [*(envelope(items) for items in invalid_items), *malformed]:
            with self.subTest(response=response):
                result = add_explanations(REQUEST, self.result, config=self.config,
                                         transport=Mock(return_value=response))
                self.assertEqual(result["explanation_status"], "invalid_response")
                self.assert_matching_unchanged(result)
                self.assertTrue(all(m["explanation_source"] == "fallback" for m in result["matches"]))

    def test_empty_outcomes_do_not_call_api_or_change_contract(self):
        for change in ({"budget": 1}, {"city": "Астана", "category": "Декоратор"}):
            request = {**REQUEST, **change}
            result = find_contractors(request, self.profiles)
            transport = Mock()
            self.assertEqual(add_explanations(request, result, config=self.config, transport=transport), result)
            transport.assert_not_called()

    def test_rare_category_and_null_hours_remain_grounded(self):
        request = {**REQUEST, "category": "Флорист", "budget": 500000, "hours": 100}
        original = find_contractors(request, self.profiles)
        result = add_explanations(request, original, config=AIConfig())
        self.assertEqual(len(result["matches"]), 2)
        for match in result["matches"]:
            self.assertIsNone(match["facts"]["hours"]["max_hours"])
            self.assertEqual(match["explanation"], explain_fallback(match["facts"]))
        self.assertEqual(result["matches"][1]["warnings"], original["matches"][1]["warnings"])

    def test_transport_uses_fixed_endpoint_timeout_and_bounded_read(self):
        response = Mock()
        response.read.return_value = b'{"status":"completed","output":[]}'
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch("backend.explanations.build_opener", return_value=opener):
            _post_openai({"model": self.config.model}, self.config)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, OPENAI_URL)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 8.0)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-only-not-a-real-key")
        response.read.assert_called_once_with(65537)
        opener.open.assert_called_once()

    def test_transport_rejects_redirects_and_oversized_responses(self):
        with self.assertRaises(HTTPError):
            _NoRedirect().redirect_request(Mock(full_url=OPENAI_URL), None, 302, "redirect", {}, "https://other.test")
        context = Mock()
        context.__enter__ = Mock(return_value=Mock(read=Mock(return_value=b"x" * 65537)))
        context.__exit__ = Mock(return_value=False)
        with patch("backend.explanations.build_opener", return_value=Mock(open=Mock(return_value=context))):
            with self.assertRaises(ValueError):
                _post_openai({}, self.config)


if __name__ == "__main__":
    unittest.main()
