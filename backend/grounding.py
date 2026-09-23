"""Проверка AI-объяснения на соответствие фактам: генерация -> проверка -> резервный шаблон.

Текст отклоняется, если в нём есть число, которого нет в facts, цитата «…», которой нет
в описании, имя подрядчика или общая фраза без содержания.
"""
import re

NUMBER = re.compile(r"\d(?:[\d   ]*\d)?")
QUOTE = re.compile(r"«([^»]+)»")
GENERIC = ("отличный выбор", "идеальный выбор", "лучший выбор", "для вашего мероприятия", "не пожалеете")


def _numbers(text: str) -> set[int]:
    return {int(re.sub(r"\D", "", m)) for m in NUMBER.findall(text)}


def _allowed_numbers(obj) -> set[int]:
    if isinstance(obj, bool) or obj is None:
        return set()
    if isinstance(obj, (int, float)):
        return {int(obj), round(obj)}
    if isinstance(obj, str):
        return _numbers(obj)
    if isinstance(obj, dict):
        return set().union(*(_allowed_numbers(v) for v in obj.values())) if obj else set()
    if isinstance(obj, (list, tuple)):
        return set().union(*(_allowed_numbers(v) for v in obj)) if obj else set()
    return set()


def check_explanation(text: str, facts: dict) -> list[str]:
    """Список проблем; пустой — текст подтверждён фактами."""
    problems = []
    if not isinstance(text, str) or not text.strip():
        return ["пустой текст"]
    low = text.casefold()
    if facts.get("name") and facts["name"].casefold() in low:
        problems.append("упомянуто имя подрядчика")
    problems += [f"общая фраза: «{g}»" for g in GENERIC if g in low]

    allowed = _allowed_numbers(facts)
    problems += [f"число не из фактов: {n}" for n in sorted(_numbers(text) - allowed)]

    highlights = [h.rstrip("….!") for h in facts.get("description_highlights", [])]
    for q in QUOTE.findall(text):
        q = q.strip().rstrip("….!")
        if not q or not any(q in h for h in highlights):
            problems.append(f"цитаты нет в описании: «{q[:40]}»")
    return problems


def verify_explanation(text: str, facts: dict) -> bool:
    return not check_explanation(text, facts)
