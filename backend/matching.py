"""Детерминированный подбор подрядчиков.

Контракт:
    find_contractors(request: dict, profiles: list[dict]) -> dict
    {
      "status": "found" | "no_category" | "none_match",
      "message": str,                       # объяснение исхода словами
      "matches":  [{"id", "profile", "match_reasons": [str], "warnings": [str]}],  # <= 3
      "excluded": [{"id", "name", "reasons": [code]}],   # кандидаты города+категории, не прошедшие условия
      "more_available": int,                # сколько ещё подходящих не вошло в топ-3
      "funnel": {...}                       # сколько кандидатов осталось после каждого шага
    }
"""
from datetime import date

MAX_RESULTS = 3

REASON_TEXT = {
    "busy_date": "занят на эту дату",
    "over_budget": "цена выше бюджета",
    "format_mismatch": "не берёт этот формат мероприятия",
    "hours_exceeded": "не работает столько часов",
    "language_mismatch": "не работает на этом языке",
}

REQUIRED_REQUEST = ("city", "date", "event_type", "category", "budget")


def _norm(s) -> str:
    return str(s or "").strip().casefold()


def _fmt_kzt(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₸"


def validate_request(request: dict) -> dict:
    missing = [f for f in REQUIRED_REQUEST if request.get(f) in (None, "")]
    if missing:
        raise ValueError(f"не заполнены обязательные поля: {missing}")
    req = dict(request)
    req["date"] = date.fromisoformat(str(request["date"])).isoformat()
    req["budget"] = int(request["budget"])
    if req["budget"] <= 0:
        raise ValueError("бюджет должен быть больше нуля")
    req["hours"] = int(request["hours"]) if request.get("hours") not in (None, "") else None
    req["language"] = request.get("language") or None
    return req


def _check(p: dict, req: dict) -> list[str]:
    """Возвращает коды причин, по которым профиль не подходит (пусто — подходит)."""
    reasons = []
    if req["date"] in p["busy_dates"]:
        reasons.append("busy_date")
    if p["price_from_kzt"] > req["budget"]:
        reasons.append("over_budget")
    if _norm(req["event_type"]) not in {_norm(f) for f in p["event_formats"]}:
        reasons.append("format_mismatch")
    if req["hours"] and p["max_hours"] is not None and p["max_hours"] < req["hours"]:
        reasons.append("hours_exceeded")
    if req["language"] and _norm(req["language"]) not in {_norm(l) for l in p["languages"]}:
        reasons.append("language_mismatch")
    return reasons


def _match_reasons(p: dict, req: dict, busy_count: int, total: int) -> list[str]:
    price, budget = p["price_from_kzt"], req["budget"]
    margin = round((budget - price) / budget * 100)
    d = date.fromisoformat(req["date"]).strftime("%d.%m.%Y")
    reasons = [
        f"Цена от {_fmt_kzt(price)} при бюджете {_fmt_kzt(budget)} — запас {margin}%.",
        f"Свободен {d}" + (f", хотя {busy_count} из {total} в этой категории заняты." if busy_count else "."),
        f"Берёт формат «{req['event_type']}».",
    ]
    if req["language"]:
        reasons.append(f"Работает на языке: {req['language']}.")
    if req["hours"]:
        if p["max_hours"] is None:
            reasons.append("Работа не привязана к часам на площадке.")
        else:
            reasons.append(f"До {p['max_hours']} ч на площадке — покрывает {req['hours']} ч.")
    return reasons


def _warnings(p: dict) -> list[str]:
    w = []
    if p.get("synthetic"):
        w.append("Синтетический профиль (не реальный подрядчик).")
    if p.get("price_imputed"):
        w.append("Цена проставлена при подготовке данных — уточните у подрядчика.")
    if p.get("city_imputed"):
        w.append("Город проставлен при подготовке данных — уточните у подрядчика.")
    return w


def find_contractors(request: dict, profiles: list[dict]) -> dict:
    req = validate_request(request)
    city, cat = _norm(req["city"]), _norm(req["category"])

    in_category = [p for p in profiles if cat in {_norm(c) for c in p["categories"]}]
    candidates = sorted((p for p in in_category if _norm(p["city"]) == city), key=lambda p: p["id"])

    funnel = {"in_city_category": len(candidates)}

    if not candidates:
        other = sorted({p["city"] for p in in_category})
        hint = f" Эта категория есть в: {', '.join(other)}." if other else " Такой категории нет в каталоге."
        return {
            "status": "no_category",
            "message": f"В городе {req['city']} нет подрядчиков категории «{req['category']}».{hint}",
            "matches": [], "excluded": [], "more_available": 0, "funnel": funnel,
        }

    checked = [(p, _check(p, req)) for p in candidates]
    passed = [p for p, r in checked if not r]
    excluded = [{"id": p["id"], "name": p["anon_name"], "reasons": r} for p, r in checked if r]

    counts = {code: sum(code in e["reasons"] for e in excluded) for code in REASON_TEXT}
    funnel.update({f"rejected_{k}": v for k, v in counts.items() if v})
    funnel["passed"] = len(passed)

    passed.sort(key=lambda p: (p["price_from_kzt"], p["id"]))
    top = passed[:MAX_RESULTS]
    busy = counts["busy_date"]
    matches = [
        {
            "id": p["id"],
            "profile": p,
            "match_reasons": _match_reasons(p, req, busy, len(candidates)),
            "warnings": _warnings(p),
        }
        for p in top
    ]

    why = "; ".join(f"{REASON_TEXT[k]} — {v}" for k, v in counts.items() if v)
    if not top:
        status = "none_match"
        message = (f"В категории «{req['category']}» ({req['city']}) {len(candidates)} кандидат(ов), "
                   f"но ни один не проходит по условиям: {why}.")
    elif len(top) < MAX_RESULTS:
        status = "found"
        message = f"Подобрано {len(top)} из {MAX_RESULTS}: всего кандидатов {len(candidates)}, остальные отсеяны ({why})."
    else:
        status = "found"
        message = f"Подобрано {len(top)} из {len(passed)} подходящих (кандидатов в категории: {len(candidates)})."

    return {
        "status": status,
        "message": message,
        "matches": matches,
        "excluded": excluded,
        "more_available": len(passed) - len(top),
        "funnel": funnel,
    }
