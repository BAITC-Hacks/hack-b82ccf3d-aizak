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

from .explain import build_facts, explain_fallback
from .grounding import check_explanation
from .ranking import rank_advantages, score_profile

MAX_RESULTS = 3

# Окно календаря занятости из кейса: вне его занятость неизвестна, свободным не считаем.
CALENDAR_START, CALENDAR_END = "2026-09-23", "2026-12-31"

REASON_TEXT = {
    "date_outside_calendar": "дата вне календаря занятости (23.09.2026–31.12.2026), доступность неизвестна",
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
    if not CALENDAR_START <= req["date"] <= CALENDAR_END:
        reasons.append("date_outside_calendar")
    elif req["date"] in p["busy_dates"]:
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


def _explain(facts: dict, explainer) -> tuple[str, str, list[str]]:
    """Генерация -> проверка по фактам -> резервный шаблон. Возвращает (текст, источник, замечания проверки)."""
    if not explainer:
        return explain_fallback(facts), "template", []
    try:
        text = explainer(facts)
    except Exception as exc:
        return explain_fallback(facts), "template", [f"AI недоступен: {type(exc).__name__}"]
    problems = check_explanation(text, facts)
    if problems:
        return explain_fallback(facts), "template_after_check", problems
    return text.strip(), "ai", []


STAGES = (  # (название этапа, коды причин, условие применения)
    ("свободен на дату", ("date_outside_calendar", "busy_date"), lambda r: True),
    ("укладывается в бюджет", ("over_budget",), lambda r: True),
    ("берёт этот формат", ("format_mismatch",), lambda r: True),
    ("работает нужное число часов", ("hours_exceeded",), lambda r: r["hours"]),
    ("работает на нужном языке", ("language_mismatch",), lambda r: r["language"]),
)


def _trace(req: dict, checked: list, shown: int) -> list[dict]:
    """Последовательная воронка: сколько кандидатов остаётся после каждого этапа."""
    trace = [{"stage": "город и категория", "remaining": len(checked)}]
    applied: set[str] = set()
    for name, codes, applies in STAGES:
        if not applies(req):
            continue
        applied.update(codes)
        trace.append({"stage": name, "remaining": sum(not applied & set(r) for _, r in checked)})
    trace.append({"stage": "ранжирование, показано", "remaining": shown})
    return trace


def _suggestions(req: dict, candidates: list[dict], shown: int) -> list[dict]:
    """Что изменить в заказе, чтобы вариантов стало больше. Только по реальным данным."""
    out = []
    if not CALENDAR_START <= req["date"] <= CALENDAR_END:
        return out
    base = date.fromisoformat(req["date"])
    for delta in (-1, 1, -2, 2, -3, 3):
        d = date.fromordinal(base.toordinal() + delta).isoformat()
        if not CALENDAR_START <= d <= CALENDAR_END:
            continue
        n = sum(not _check(p, {**req, "date": d}) for p in candidates)
        if n > shown:
            out.append({"type": "date", "value": d, "available": n,
                        "text": f"{date.fromisoformat(d).strftime('%d.%m.%Y')} подходят {n}"})
        if sum(s["type"] == "date" for s in out) == 2:
            break
    only_budget = [p for p in candidates if _check(p, req) == ["over_budget"]]
    if only_budget:
        need = min(p["price_from_kzt"] for p in only_budget)
        gain = sum(p["price_from_kzt"] <= need for p in only_budget)
        out.append({"type": "budget", "value": need, "available": shown + gain,
                    "text": f"при бюджете от {need:,} ₸ (+{need - req['budget']:,} ₸) добавится вариантов: {gain}".replace(",", " ")})
    return out


def find_contractors(request: dict, profiles: list[dict], explainer=None, similarity=None) -> dict:
    """explainer: facts -> str (AI-модуль), проверяется по фактам; на порядок не влияет.
    similarity: {id: 0..1} или функция request -> {id: 0..1} (эмбеддинги AI-модуля) — компонента ранжирования.
    """
    req = validate_request(request)
    if callable(similarity):
        try:
            similarity = similarity(req)
        except Exception:
            similarity = None
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
            "suggestions": [{"type": "city", "value": c, "text": f"категория есть в городе {c}"} for c in other],
            "trace": [{"stage": "город и категория", "remaining": 0}],
        }

    checked = [(p, _check(p, req)) for p in candidates]
    passed = [p for p, r in checked if not r]
    excluded = [{"id": p["id"], "name": p["anon_name"], "reasons": r} for p, r in checked if r]

    counts = {code: sum(code in e["reasons"] for e in excluded) for code in REASON_TEXT}
    funnel.update({f"rejected_{k}": v for k, v in counts.items() if v})
    funnel["passed"] = len(passed)

    scores = {p["id"]: score_profile(p, req, similarity) for p in passed}
    passed.sort(key=lambda p: (-scores[p["id"]][0], p["price_from_kzt"], p["id"]))
    top = passed[:MAX_RESULTS]
    busy = counts["busy_date"]
    availability = {"busy_in_category": busy, "candidates": len(candidates)}
    matches = []
    for i, p in enumerate(top):
        score, components = scores[p["id"]]
        nxt = passed[i + 1] if i + 1 < len(passed) else None
        advantages = rank_advantages(components, scores[nxt["id"]][1] if nxt else None)
        facts = build_facts(p, req, [q for q in top if q is not p], availability)
        facts["ranking"] = {"rank": i + 1, "score": score, "components": components,
                            "above_next_because": advantages}
        explanation, source, check = _explain(facts, explainer)
        reasons = _match_reasons(p, req, busy, len(candidates))
        if advantages:
            reasons.append(f"Место {i + 1}: выше следующего — {', '.join(advantages)}.")
        matches.append({
            "id": p["id"],
            "profile": p,
            "explanation": explanation,
            "explanation_source": source,
            "explanation_check": check,
            "facts": facts,
            "match_reasons": reasons,
            "warnings": _warnings(p),
        })

    why = "; ".join(f"{REASON_TEXT[k]} — {v}" for k, v in counts.items() if v)
    if not top:
        status = "none_match"
        message = (f"В категории «{req['category']}» ({req['city']}) {len(candidates)} кандидат(ов), "
                   f"но ни один не проходит по условиям: {why}.")
    elif len(top) < MAX_RESULTS:
        status = "found"
        message = f"Подобрано {len(top)} из {MAX_RESULTS}: в городе {req['city']} всего {len(candidates)} подрядчик(ов) категории «{req['category']}»"
        message += f", остальные отсеяны ({why})." if why else "."
    else:
        status = "found"
        message = f"Подобрано {len(top)} из {len(passed)} подходящих (кандидатов в категории: {len(candidates)})."
    if len(top) == MAX_RESULTS and busy:  # при <3 занятость уже есть в перечне причин
        d = date.fromisoformat(req["date"]).strftime("%d.%m.%Y")
        message += f" На {d} заняты {busy} из {len(candidates)}."

    return {
        "status": status,
        "message": message,
        "matches": matches,
        "excluded": excluded,
        "more_available": len(passed) - len(top),
        "funnel": funnel,
        "suggestions": _suggestions(req, candidates, len(top)) if len(top) < MAX_RESULTS else [],
        "trace": _trace(req, checked, len(top)),
    }
