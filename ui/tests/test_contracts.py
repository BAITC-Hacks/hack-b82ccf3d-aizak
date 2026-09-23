"""Offline request, response and injectable-provider checks."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog import CALENDAR_END, CALENDAR_START, demo_catalog
from contracts import BackendError, ContractError, RequestError, validate_result
from mock_data import DEMO_PROFILES, search_contractors
from service import SearchService, make_backend_service

REQUEST = {
    "city": "Астана", "category": "Ведущий", "event_type": "свадьба",
    "date": "2026-10-11", "budget": 200000, "language": None, "hours": None,
}


class ContractTests(unittest.TestCase):
    def test_request_keys_and_optional_nulls_reach_provider(self):
        provider = Mock(return_value=search_contractors(REQUEST))
        SearchService(provider, demo_catalog()).search(REQUEST)
        self.assertEqual(provider.call_args.args, (REQUEST,))

    def test_invalid_inputs_never_reach_provider(self):
        for change in (
            {"budget": 0}, {"budget": True}, {"budget": 2.5}, {"date": "not-a-date"},
            {"date": "2027-01-01"}, {"date": "2026-09-22"}, {"hours": -1},
            {"language": "invented"}, {"city": "invented"}, {"category": None},
        ):
            with self.subTest(change=change):
                provider = Mock()
                with self.assertRaises(RequestError):
                    SearchService(provider, demo_catalog()).search({**REQUEST, **change})
                provider.assert_not_called()

    def test_envelope_for_all_three_outcomes(self):
        for change, status in (({}, "found"), ({"city": "Зарубежье"}, "no_category"), ({"budget": 1}, "none_match")):
            result = SearchService(search_contractors, demo_catalog()).search({**REQUEST, **change})
            self.assertEqual(result["status"], status)
            self.assertEqual(set(result), {"status", "message", "matches", "excluded", "more_available", "funnel"})

    def test_invalid_envelopes_rejected(self):
        base = search_contractors(REQUEST)
        for change in (
            {"matches": None}, {"excluded": None}, {"funnel": []}, {"message": None},
            {"status": "none_match"}, {"status": "unknown"}, {"more_available": -1},
            {"matches": base["matches"] + [base["matches"][0]]},
            {"matches": [base["matches"][0], base["matches"][0]]},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ContractError):
                    validate_result({**base, **change})
        for field in base:
            invalid = deepcopy(base)
            del invalid[field]
            with self.assertRaises(ContractError):
                validate_result(invalid)

    def test_invalid_profile_and_reasons_are_not_rendered(self):
        for field, value in (("anon_name", None), ("price_from_kzt", "80000"), ("synthetic", "False"), ("categories", None)):
            invalid = search_contractors(REQUEST)
            invalid["matches"][0]["profile"][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_result(invalid)
        invalid = search_contractors(REQUEST)
        invalid["matches"][0]["match_reasons"] = []
        with self.assertRaises(ContractError):
            validate_result(invalid)

    def test_backend_failure_does_not_return_mock_results(self):
        provider = Mock(side_effect=TimeoutError("private internal path"))
        with self.assertRaises(BackendError) as caught:
            SearchService(provider, demo_catalog()).search(REQUEST)
        self.assertNotIn("private", str(caught.exception))
        provider.assert_called_once()

    def test_adapter_passes_profiles_and_builds_catalog(self):
        finder = Mock(return_value=search_contractors(REQUEST))
        service = make_backend_service(finder, DEMO_PROFILES)
        service.search(REQUEST)
        finder.assert_called_once_with(REQUEST, DEMO_PROFILES)
        self.assertFalse(service.is_demo)
        self.assertIn("Фотограф", service.catalog["category"])

    def test_budget_boundary_calendar_boundary_and_null_duration(self):
        service = SearchService(search_contractors, demo_catalog())
        self.assertEqual(len(service.search({**REQUEST, "budget": 80000})["matches"]), 1)
        for day in (CALENDAR_START, CALENDAR_END):
            self.assertEqual(service.search({**REQUEST, "date": day.isoformat()})["status"], "found")
        result = service.search({**REQUEST, "city": "Алматы", "category": "Декоратор", "hours": 100})
        self.assertEqual(len(result["matches"]), 1)
        self.assertTrue(any("не привязана" in reason for reason in result["matches"][0]["match_reasons"]))

    def test_demo_results_do_not_mutate_fixtures(self):
        before = deepcopy(DEMO_PROFILES)
        response = search_contractors(REQUEST)
        response["matches"][0]["profile"]["categories"].append("changed")
        self.assertEqual(DEMO_PROFILES, before)


BACKEND_CONTRACT_FILE = Path(os.environ.get("AIZAK_BACKEND_CONTRACT_FILE") or
                             Path(__file__).resolve().parents[2] / "backend" / "matching.py")


@unittest.skipUnless(BACKEND_CONTRACT_FILE.is_file(), "Backend not present in standalone UI checkout")
class BackendCompatibilityTests(unittest.TestCase):
    def test_mock_matches_actual_backend_structure_and_filters_offline(self):
        spec = importlib.util.spec_from_file_location("aizak_backend_contract", BACKEND_CONTRACT_FILE)
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        for change in (
            {}, {"budget": 1}, {"budget": 80000}, {"city": "Зарубежье"},
            {"category": "Флорист"}, {"date": "2026-10-10"}, {"event_type": "той"},
            {"language": "английский"}, {"hours": 12}, {"hours": 6, "language": "казахский"},
            {"city": "Алматы", "category": "Декоратор", "hours": 100},
        ):
            request = {**REQUEST, **change}
            with self.subTest(change=change):
                actual = validate_result(backend.find_contractors(request, deepcopy(DEMO_PROFILES)))
                demo = validate_result(search_contractors(request))
                self.assertEqual(set(actual), set(demo))
                for field in ("status", "more_available", "funnel"):
                    self.assertEqual(actual[field], demo[field])
                self.assertEqual([m["id"] for m in actual["matches"]], [m["id"] for m in demo["matches"]])
                self.assertEqual({e["id"]: sorted(e["reasons"]) for e in actual["excluded"]}, {e["id"]: sorted(e["reasons"]) for e in demo["excluded"]})
                for real_match, demo_match in zip(actual["matches"], demo["matches"]):
                    self.assertEqual(set(real_match), set(demo_match))
                    self.assertEqual(real_match["profile"], demo_match["profile"])


if __name__ == "__main__":
    unittest.main()
