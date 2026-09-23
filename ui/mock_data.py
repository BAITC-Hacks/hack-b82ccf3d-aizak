"""Explicitly fictional fixtures, never records from the competition dataset.

Response fields follow backend/matching.py on feature/matching at 3220b61.
This demonstration provider is intentionally independent of backend code.
"""

from copy import deepcopy
from datetime import date

from catalog import CATEGORIES, CITIES, EVENT_TYPES, LANGUAGES, REASON_LABELS


def _profile(identifier, name, city, category, price, max_hours=8):
    return {
        "id": identifier,
        "anon_name": name,
        "city": city,
        "categories": [category],
        "price_from_kzt": price,
        "event_formats": ["свадьба", "корпоратив", "день рождения"],
        "languages": ["русский", "казахский"],
        "max_hours": max_hours,
        "busy_dates": ["2026-10-10"],
        "synthetic": True,
        "price_imputed": False,
        "city_imputed": False,
        "description": "Вымышленный профиль для проверки интерфейса AIZAK.",
    }


DEMO_PROFILES = [
    _profile("demo-001", "Тестовый ведущий 01", "Астана", "Ведущий", 80000),
    _profile("demo-002", "Тестовый ведущий 02", "Астана", "Ведущий", 120000),
    _profile("demo-003", "Тестовый ведущий 03", "Астана", "Ведущий", 160000),
    _profile("demo-004", "Тестовый ведущий 04", "Астана", "Ведущий", 180000),
    _profile("demo-005", "Тестовый фотограф 01", "Алматы", "Фотограф", 90000),
    _profile("demo-006", "Тестовый декоратор 01", "Алматы", "Декоратор", 130000, max_hours=None),
]


def format_kzt(value):
    return f"{int(value):,}".replace(",", " ") + " ₸"


def search_contractors(request):
    """Return a deterministic, JSON-serializable demonstration response."""
    event_date = date.fromisoformat(request["date"])
    budget = int(request["budget"])
    if budget <= 0:
        raise ValueError("Бюджет должен быть больше нуля.")
    def normalized(value):
        return str(value or "").strip().casefold()

    candidates = sorted([
        p for p in DEMO_PROFILES
        if normalized(p["city"]) == normalized(request["city"])
        and normalized(request["category"]) in {normalized(c) for c in p["categories"]}
    ], key=lambda p: p["id"])
    matches, excluded = [], []
    for profile in candidates:
        reasons = []
        if profile["price_from_kzt"] > budget:
            reasons.append("over_budget")
        if request["date"] in profile["busy_dates"]:
            reasons.append("busy_date")
        if normalized(request["event_type"]) not in {normalized(f) for f in profile["event_formats"]}:
            reasons.append("format_mismatch")
        if request.get("language") and normalized(request["language"]) not in {normalized(v) for v in profile["languages"]}:
            reasons.append("language_mismatch")
        if request.get("hours") and profile["max_hours"] is not None and request["hours"] > profile["max_hours"]:
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
            match_reasons.append(
                "Работа не привязана к часам на площадке." if profile["max_hours"] is None
                else f"До {profile['max_hours']} ч работы: покрывает ваши {request['hours']} ч."
            )
        matches.append({
            "id": profile["id"], "profile": deepcopy(profile), "match_reasons": match_reasons,
            "warnings": ["Тестовые данные: это не реальный подрядчик."],
        })
    matches.sort(key=lambda m: (m["profile"]["price_from_kzt"], m["id"]))
    counts = {code: sum(code in e["reasons"] for e in excluded) for code in REASON_LABELS}
    funnel = {"in_city_category": len(candidates)}
    if candidates:
        funnel.update({f"rejected_{code}": count for code, count in counts.items() if count})
        funnel["passed"] = len(matches)
    why = "; ".join(f"{REASON_LABELS[code]} — {count}" for code, count in counts.items() if count)
    if not candidates:
        status = "no_category"
        message = f"В городе {request['city']} нет категории «{request['category']}» в текущем каталоге."
    elif not matches:
        status = "none_match"
        message = f"Категория есть: {len(candidates)} кандидат(ов), но никто не прошёл условия: {why}."
    else:
        status = "found"
        message = f"Подобрано {min(3, len(matches))} из {len(matches)} подходящих."
        if len(matches) < 3:
            message += (f" Остальные исключены: {why}." if excluded else " В каталоге этой категории больше кандидатов нет.")
    return {
        "status": status,
        "message": message,
        "matches": matches[:3],
        "excluded": excluded,
        "more_available": max(0, len(matches) - 3),
        "funnel": funnel,
    }
