"""Frontend boundary for Alibek's find_contractors contract v1 at 559a322."""
from datetime import date
from typing import Literal, TypedDict


class SearchRequest(TypedDict):
    city: str
    category: str
    date: str
    event_type: str
    budget: int
    language: str | None
    hours: int | None


class ExplanationFields(TypedDict, total=False):
    explanation: str
    explanation_source: Literal["openai", "fallback"]


class Match(ExplanationFields):
    id: str
    profile: dict
    match_reasons: list[str]
    warnings: list[str]


class ExplanationStatus(TypedDict, total=False):
    explanation_status: str


class SearchResult(ExplanationStatus):
    status: Literal["found", "no_category", "none_match"]
    message: str
    matches: list[Match]
    excluded: list[dict]
    more_available: int
    funnel: dict[str, int]


class RequestError(ValueError):
    """User input cannot be sent to the provider."""


class ContractError(ValueError):
    """Provider response is not safe to render as a successful search."""


class BackendError(RuntimeError):
    """Provider failed; do not replace its result with demo data."""


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def validate_request(raw, catalog, calendar_start, calendar_end) -> SearchRequest:
    if not isinstance(raw, dict):
        raise RequestError("Проверьте параметры мероприятия.")
    result = {}
    for field, label in (("city", "город"), ("category", "категорию"), ("event_type", "формат мероприятия")):
        value = raw.get(field)
        if not isinstance(value, str) or value not in catalog[field]:
            raise RequestError(f"Выберите {label} из списка.")
        result[field] = value
    try:
        selected_date = date.fromisoformat(raw["date"])
    except (TypeError, ValueError, KeyError):
        raise RequestError("Укажите корректную дату мероприятия.") from None
    if not calendar_start <= selected_date <= calendar_end:
        raise RequestError(f"Календарь доступен с {calendar_start:%d.%m.%Y} по {calendar_end:%d.%m.%Y}. Выберите дату в этом диапазоне.")
    if not _integer(raw.get("budget"), 1):
        raise RequestError("Бюджет должен быть целым положительным числом в тенге.")
    hours = raw.get("hours")
    if hours is not None and not _integer(hours, 1):
        raise RequestError("Укажите положительную длительность либо оставьте её пустой.")
    language = raw.get("language")
    if language is not None and language not in catalog["language"]:
        raise RequestError("Выберите язык из списка либо не задавайте ограничение.")
    result.update(date=selected_date.isoformat(), budget=raw["budget"], hours=hours, language=language)
    return result


def validate_result(raw) -> SearchResult:
    """Reject bad envelopes instead of crashing, inventing prices or hiding errors."""
    message = "Сервис вернул некорректный результат. Попробуйте ещё раз или сообщите команде."

    def require(condition):
        if not condition:
            raise ContractError(message)

    def strings(value, nonempty=False):
        return isinstance(value, list) and (not nonempty or bool(value)) and all(isinstance(v, str) and bool(v.strip()) for v in value)

    require(isinstance(raw, dict))
    require(all(k in raw for k in ("status", "message", "matches", "excluded", "more_available", "funnel")))
    require(raw["status"] in ("found", "no_category", "none_match"))
    require(isinstance(raw["message"], str) and bool(raw["message"].strip()))
    require(isinstance(raw["matches"], list) and len(raw["matches"]) <= 3)
    require(isinstance(raw["excluded"], list))
    require(_integer(raw["more_available"]))
    require(isinstance(raw["funnel"], dict) and "in_city_category" in raw["funnel"])
    require(all(isinstance(k, str) and _integer(v) for k, v in raw["funnel"].items()))
    require((raw["status"] == "found") == bool(raw["matches"]))
    if "explanation_status" in raw:
        require(raw["explanation_status"] in ("openai", "disabled", "missing_key",
                "configuration_error", "api_unavailable", "invalid_response"))
    if raw["status"] != "found":
        require(raw["more_available"] == 0)
    if raw["status"] == "no_category":
        require(raw["funnel"]["in_city_category"] == 0 and not raw["excluded"])
    if raw["status"] == "none_match":
        require(raw["funnel"]["in_city_category"] > 0)
    seen = set()
    for match in raw["matches"]:
        require(isinstance(match, dict))
        identifier = match.get("id")
        require(isinstance(identifier, str) and bool(identifier.strip()))
        require(identifier not in seen)
        seen.add(identifier)
        require(strings(match.get("match_reasons"), nonempty=True))
        require(strings(match.get("warnings")))
        if "explanation" in match or "explanation_source" in match:
            require(isinstance(match.get("explanation"), str) and bool(match["explanation"].strip()))
            require(match.get("explanation_source") in ("openai", "fallback"))
        profile = match.get("profile")
        require(isinstance(profile, dict))
        require(profile.get("id") == identifier)
        for field in ("anon_name", "city"):
            require(isinstance(profile.get(field), str) and bool(profile[field].strip()))
        require(strings(profile.get("categories"), nonempty=True))
        require(_integer(profile.get("price_from_kzt")))
        for field in ("synthetic", "price_imputed", "city_imputed"):
            require(type(profile.get(field)) is bool)
    for item in raw["excluded"]:
        require(isinstance(item, dict))
        require(isinstance(item.get("id"), str) and bool(item["id"].strip()))
        require(item["id"] not in seen)
        seen.add(item["id"])
        require(isinstance(item.get("name"), str) and bool(item["name"].strip()))
        require(strings(item.get("reasons"), nonempty=True))
    return raw
