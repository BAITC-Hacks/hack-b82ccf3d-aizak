"""UI option values observed in feature/matching at 3220b61; no profile records."""
from datetime import date

CITIES = ("Астана", "Алматы", "Зарубежье")
CATEGORIES = (
    "Ведущий", "Банкетный зал", "Ведущий церемонии", "Видеограф", "Декоратор",
    "Загородная площадка", "Инструменталист", "Лайв-бэнд", "Национальный ансамбль",
    "Отель", "Подарки и сувениры", "Ресторан", "Танцевальный коллектив", "Флорист",
    "Фото и видеобудки", "Фотограф", "Шоу-программа",
)
EVENT_TYPES = ("свадьба", "той", "корпоратив", "конференция", "юбилей", "день рождения")
LANGUAGES = ("русский", "казахский", "английский")
# The live service receives the same bounds from backend.matching.
CALENDAR_START = date(2026, 9, 23)
CALENDAR_END = date(2026, 12, 31)
REASON_LABELS = {
    "date_outside_calendar": "дата вне календаря занятости, доступность неизвестна",
    "busy_date": "занят на выбранную дату",
    "over_budget": "стартовая цена выше бюджета",
    "format_mismatch": "не подходит формат мероприятия",
    "hours_exceeded": "не подходит длительность",
    "language_mismatch": "не подходит язык",
}


def demo_catalog():
    return {"city": CITIES, "category": CATEGORIES, "event_type": EVENT_TYPES, "language": LANGUAGES}


def catalog_from_profiles(profiles):
    """Build actual options from normalized profiles when the backend is wired in."""
    fields = {"city": "city", "category": "categories", "event_type": "event_formats", "language": "languages"}
    return {
        key: tuple(sorted({value for p in profiles for value in ([p[field]] if key == "city" else p[field])}))
        for key, field in fields.items()
    }
