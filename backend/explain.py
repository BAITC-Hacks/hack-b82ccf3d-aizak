"""Структурированные факты о выбранном подрядчике и шаблонное объяснение.

build_facts() — вход для AI-модуля: только данные из профиля и сравнения с соседями по выдаче.
explain_fallback() — резервное объяснение без модели.
"""
import re

EVENT_PATTERNS = {
    "свадьба": r"свад|венча|никах|молодожен|жених|невест",
    "той": r"\bто[йяеюи]|узату|сундет|беташар|кыз\s*узату",
    "корпоратив": r"корпорат|компани|бизнес|сотрудник",
    "конференция": r"конференц|форум|делов|бизнес|спикер",
    "юбилей": r"юбиле",
    "день рождения": r"день\s+рожден|дн[ейя]\s+рожден|детск",
}
LANGUAGE_PATTERNS = {"казахский": r"казах|қазақ", "английский": r"англ|english", "русский": r"русск"}
EXPERIENCE = re.compile(
    r"\d+\s*(?:\+\s*)?(?:лет|года?)\b|опыт|\d[\d\s]*\s*(?:свад|мероприят|проект|гост|человек|заказ|клиент|событи)",
    re.IGNORECASE,
)
MAX_HIGHLIGHT = 130


def _fmt_kzt(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₸"


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|[•\n;]+", text)
    out = []
    for s in parts:
        s = " ".join(s.split()).strip(" -–—:")
        if len(s) < 15:
            continue
        if len(s) > MAX_HIGHLIGHT:
            s = s[:MAX_HIGHLIGHT].rsplit(" ", 1)[0] + "…"
        out.append(s)
    return out


def description_highlights(description: str, event_type: str, language: str | None = None,
                           limit: int = 2, exclude: str | None = None) -> list[str]:
    """Дословные фрагменты описания про нужный формат, опыт или язык. Нет таких — пустой список.

    exclude — имя подрядчика: фрагменты с ним пропускаются, чтобы карточку отличали факты, а не имя.
    """
    ev = EVENT_PATTERNS.get(event_type.strip().casefold())
    lang = LANGUAGE_PATTERNS.get((language or "").strip().casefold())
    scored = []
    for pos, s in enumerate(_sentences(description)):
        if exclude and exclude.casefold() in s.casefold():
            continue
        score = 0
        if ev and re.search(ev, s, re.IGNORECASE):
            score += 2
        if EXPERIENCE.search(s):
            score += 1
        if lang and re.search(lang, s, re.IGNORECASE):
            score += 1
        if score:
            scored.append((-score, pos, s))
    return [s for _, _, s in sorted(scored)[:limit]]


def _distinctive(p: dict, req: dict, peers: list[dict]) -> list[str]:
    """Проверяемые отличия от других подрядчиков той же выдачи."""
    if not peers:
        return []
    out = []
    peer_prices = [q["price_from_kzt"] for q in peers]
    if p["price_from_kzt"] < min(peer_prices):
        out.append(f"самый низкий старт среди подобранных — на {_fmt_kzt(min(peer_prices) - p['price_from_kzt'])} дешевле следующего")
    elif p["price_from_kzt"] > max(peer_prices):
        out.append(f"самый дорогой из подобранных — на {_fmt_kzt(p['price_from_kzt'] - max(peer_prices))} выше")

    peer_langs = {l.casefold() for q in peers for l in q["languages"]}
    uniq_langs = [l for l in p["languages"] if l.casefold() not in peer_langs]
    if uniq_langs:
        out.append(f"единственный из подобранных работает на языке: {', '.join(uniq_langs)}")

    peer_formats = {f.casefold() for q in peers for f in q["event_formats"]}
    uniq_formats = [f for f in p["event_formats"] if f.casefold() not in peer_formats]
    if uniq_formats:
        out.append(f"единственный из подобранных берёт также: {', '.join(uniq_formats)}")

    peer_hours = [q["max_hours"] for q in peers]
    if p["max_hours"] is None and any(h is not None for h in peer_hours):
        out.append("работа не привязана к часам на площадке, в отличие от остальных")
    elif p["max_hours"] is not None and all(h is not None and h < p["max_hours"] for h in peer_hours):
        out.append(f"дольше всех подобранных на площадке — до {p['max_hours']} ч")

    extra = [c for c in p["categories"] if c.casefold() != req["category"].strip().casefold()]
    if extra:
        out.append(f"также работает как: {', '.join(extra)}")
    return out


def build_facts(profile: dict, request: dict, peers: list[dict] | None = None,
                availability: dict | None = None) -> dict:
    """Факты для объяснения одной карточки.

    profile — нормализованный профиль; request — валидированный запрос;
    peers — остальные подрядчики этой же выдачи; availability — {"busy_in_category", "candidates"}.
    """
    p, req = profile, request
    budget, price = req["budget"], p["price_from_kzt"]
    return {
        "id": p["id"],
        "name": p["anon_name"],
        "category": req["category"],
        "city": p["city"],
        "price": {
            "from_kzt": price,
            "budget_kzt": budget,
            "margin_pct": round((budget - price) / budget * 100),
            "imputed": p.get("price_imputed", False),
        },
        "availability": {"date": req["date"], "free": True, **(availability or {})},
        "event_format": {"requested": req["event_type"], "accepted": list(p["event_formats"])},
        "languages": {
            "all": list(p["languages"]),
            "requested": req.get("language"),
        },
        "hours": {"max_hours": p["max_hours"], "requested": req.get("hours")},
        "description_highlights": description_highlights(
            p.get("description", ""), req["event_type"], req.get("language"), exclude=p["anon_name"]),
        "distinctive": _distinctive(p, req, peers or []),
        "provenance": {
            "synthetic": p.get("synthetic", False),
            "price_imputed": p.get("price_imputed", False),
            "city_imputed": p.get("city_imputed", False),
        },
    }


def explain_fallback(facts: dict) -> str:
    """1–2 предложения только из facts; без общих фраз."""
    pr = facts["price"]
    first = f"От {_fmt_kzt(pr['from_kzt'])} — запас {pr['margin_pct']}% бюджета"
    if facts["distinctive"]:
        first += "; " + "; ".join(facts["distinctive"][:2])
    else:
        h = facts["hours"]
        if h["requested"]:
            first += ("; работа не привязана к часам" if h["max_hours"] is None
                      else f"; до {h['max_hours']} ч на площадке при нужных {h['requested']} ч")
        if facts["languages"]["requested"]:
            first += f"; работает на языке: {facts['languages']['requested']}"
    first += "."
    if facts["description_highlights"]:
        second = f"Из описания: «{facts['description_highlights'][0].rstrip('.!')}»"
    else:
        second = f"Берёт форматы: {', '.join(facts['event_format']['accepted'])}"
    if not second.endswith((".", "!", "?")):
        second += "."
    return f"{first} {second}"
