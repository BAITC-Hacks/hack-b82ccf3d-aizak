"""Прозрачное ранжирование: итоговый балл = сумма взвешенных компонент, каждая в [0, 1].

Все компоненты вычисляются из профиля и запроса, поэтому порядок детерминирован и объясним.
semantic — сходство описания с запросом от AI-модуля (эмбеддинги); без него = 0.
"""
import re
import math

from .explain import EVENT_PATTERNS, EXPERIENCE

WEIGHTS = {
    "format_specialization": 0.35,  # описание прямо говорит о нужном формате
    "price_fit": 0.25,              # доля бюджета, которая остаётся
    "semantic": 0.15,               # смысловая близость описания к запросу
    "flexibility": 0.15,            # языки и запас по часам
    "experience": 0.10,             # в описании есть опыт/цифры/объёмы
}

LABELS = {
    "format_specialization": "описание прямо про этот формат",
    "price_fit": "больший запас бюджета",
    "semantic": "описание ближе по смыслу к запросу",
    "flexibility": "больше языков и запас по часам",
    "experience": "в описании указан опыт",
}


def score_profile(p: dict, req: dict, similarity: dict | None = None) -> tuple[float, dict]:
    desc = p.get("description", "")
    pattern = EVENT_PATTERNS.get(req["event_type"].strip().casefold())
    hours = 1.0 if p["max_hours"] is None else min(p["max_hours"], 12) / 12
    # An optional/failed semantic provider must never break the deterministic MVP.
    semantic = similarity.get(p["id"], 0.0) if isinstance(similarity, dict) else 0.0
    try:
        semantic = float(semantic)
        semantic = max(0.0, min(1.0, semantic)) if math.isfinite(semantic) else 0.0
    except (ValueError, TypeError, OverflowError):
        semantic = 0.0
    components = {
        "format_specialization": 1.0 if pattern and re.search(pattern, desc, re.IGNORECASE) else 0.0,
        "price_fit": max(0.0, 1 - p["price_from_kzt"] / req["budget"]),
        "semantic": semantic,
        "flexibility": 0.5 * min(len(p["languages"]), 3) / 3 + 0.5 * hours,
        "experience": 1.0 if EXPERIENCE.search(desc) else 0.0,
    }
    components = {k: round(v, 4) for k, v in components.items()}
    score = round(sum(WEIGHTS[k] * v for k, v in components.items()), 4)
    return score, components


def rank_advantages(components: dict, next_components: dict | None) -> list[str]:
    """Почему карточка стоит выше следующей: компоненты, где вклад заметно больше."""
    if not next_components:
        return []
    gains = sorted(
        ((WEIGHTS[k] * (components[k] - next_components[k]), k) for k in WEIGHTS),
        reverse=True,
    )
    return [LABELS[k] for gain, k in gains if gain >= 0.01][:2]
