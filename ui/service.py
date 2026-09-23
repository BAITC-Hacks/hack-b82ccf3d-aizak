"""Injectable local provider boundary. No HTTP or OpenAI API calls."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sys
from typing import Callable

from catalog import CALENDAR_END, CALENDAR_START, catalog_from_profiles
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
    """Load the official dataset and use the team's local matching backend."""
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from backend import find_contractors, load_profiles
    from backend.matching import CALENDAR_END as end, CALENDAR_START as start

    try:
        profiles = load_profiles()
    except (OSError, ValueError):
        raise BackendError(
            "Не удалось загрузить каталог подрядчиков. Проверьте наличие и формат "
            "официального датасета; при нестандартном пути задайте AIZAK_DATASET."
        ) from None
    return make_backend_service(
        find_contractors, profiles,
        calendar_start=date.fromisoformat(start), calendar_end=date.fromisoformat(end),
    )
