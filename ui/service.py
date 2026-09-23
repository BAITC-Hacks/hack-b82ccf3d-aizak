"""Injectable local provider boundary. No HTTP or OpenAI API calls."""
from dataclasses import dataclass
from datetime import date
from typing import Callable

from catalog import CALENDAR_END, CALENDAR_START, catalog_from_profiles, demo_catalog
from contracts import BackendError, SearchRequest, SearchResult, validate_request, validate_result


@dataclass
class SearchService:
    provider: Callable[[SearchRequest], SearchResult]
    catalog: dict
    is_demo: bool = False
    calendar_start: date = CALENDAR_START
    calendar_end: date = CALENDAR_END

    def search(self, raw_request):
        request = validate_request(raw_request, self.catalog, self.calendar_start, self.calendar_end)
        try:
            result = self.provider(request)
        except Exception:
            # Do not expose internal paths, credentials or upstream error bodies.
            raise BackendError("Сервис подбора временно недоступен. Попробуйте повторить поиск.") from None
        return validate_result(result)


def make_backend_service(find_contractors, profiles, *, calendar_start=CALENDAR_START, calendar_end=CALENDAR_END):
    """Wire the existing local backend after integration, without touching it.

    Example for the integrator:
        make_backend_service(find_contractors, load_profiles())
    This function performs no imports, reads or requests to a real backend.
    """
    return SearchService(
        provider=lambda request: find_contractors(request, profiles),
        catalog=catalog_from_profiles(profiles),
        calendar_start=calendar_start, calendar_end=calendar_end,
    )


def get_search_service():
    """The live UI remains explicitly in demo mode until team integration."""
    from mock_data import search_contractors
    return SearchService(search_contractors, demo_catalog(), is_demo=True)
