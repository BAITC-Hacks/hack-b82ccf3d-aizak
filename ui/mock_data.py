"""Explicitly fictional fixtures, never records from the competition dataset.

Response fields follow backend/matching.py on feature/matching at 3220b61.
This demonstration provider is intentionally independent of backend code.
"""

from datetime import date


def _profile(identifier, name, city, category, price, max_hours=8):
    return {
        "id": identifier,
        "anon_name": name,
        "city": city,
        "categories": [category],
        "price_from_kzt": price,
        "event_formats": ["Свадьба", "Корпоратив", "День рождения"],
        "languages": ["Русский", "Казахский"],
        "max_hours": max_hours,
        "busy_dates": ["2030-01-15"],
        "synthetic": True,
        "description": "Вымышленный профиль для проверки интерфейса AIZAK.",
    }


DEMO_PROFILES = [
    _profile("demo-001", "Тестовый ведущий 01", "Астана", "Ведущий", 80000),
    _profile("demo-002", "Тестовый ведущий 02", "Астана", "Ведущий", 120000),
    _profile("demo-003", "Тестовый ведущий 03", "Астана", "Ведущий", 160000),
    _profile("demo-004", "Тестовый ведущий 04", "Астана", "Ведущий", 180000),
    _profile("demo-005", "Тестовый фотограф 01", "Алматы", "Фотограф", 90000),
    _profile("demo-006", "Тестовый декоратор 01", "Шымкент", "Декоратор", 130000),
]
CITIES = ["Астана", "Алматы", "Шымкент"]
CATEGORIES = ["Ведущий", "Фотограф", "Декоратор"]
EVENT_TYPES = ["Свадьба", "Корпоратив", "День рождения"]
LANGUAGES = ["Русский", "Казахский"]


def format_kzt(value):
    return f"{int(value):,}".replace(",", " ") + " ₸"


def search_contractors(request):
    """Return a deterministic, JSON-serializable demonstration response."""
    event_date = date.fromisoformat(request["date"])
    budget = int(request["budget"])
    if budget <= 0:
        raise ValueError("Бюджет должен быть больше нуля.")
    candidates = [
        p for p in DEMO_PROFILES
        if p["city"] == request["city"] and request["category"] in p["categories"]
    ]
    matches, excluded = [], []
    for profile in sorted(candidates, key=lambda p: (p["price_from_kzt"], p["id"])):
        reasons = []
        if profile["price_from_kzt"] > budget:
            reasons.append("over_budget")
        if request["date"] in profile["busy_dates"]:
            reasons.append("busy_date")
        if request["event_type"] not in profile["event_formats"]:
            reasons.append("format_mismatch")
        if request.get("language") and request["language"] not in profile["languages"]:
            reasons.append("language_mismatch")
        if request.get("hours") and request["hours"] > profile["max_hours"]:
            reasons.append("hours_exceeded")
        if reasons:
            excluded.append({"id": profile["id"], "name": profile["anon_name"], "reasons": reasons})
            continue
        match_reasons = [
            f"Город: {profile['city']}; категория: {request['category']}.",
            f"Стартовая цена {format_kzt(profile['price_from_kzt'])} укладывается в бюджет {format_kzt(budget)}.",
            f"По тестовому календарю свободен {event_date:%d.%m.%Y}.",
            f"Подходит формат «{request['event_type']}».",
        ]
        if request.get("language"):
            match_reasons.append(f"Язык: {request['language']}.")
        if request.get("hours"):
            match_reasons.append(f"До {profile['max_hours']} ч работы: покрывает ваши {request['hours']} ч.")
        matches.append({
            "id": profile["id"], "profile": dict(profile), "match_reasons": match_reasons,
            "warnings": ["Тестовые данные: это не реальный подрядчик."],
        })
    return {
        "status": "found" if matches else ("none_match" if candidates else "no_category"),
        "message": "Демонстрационная выдача на вымышленных профилях.",
        "matches": matches[:3],
        "excluded": excluded,
        "more_available": max(0, len(matches) - 3),
    }
