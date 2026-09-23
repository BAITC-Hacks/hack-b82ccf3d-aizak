"""Загрузка и валидация профилей подрядчиков (CSV или JSONL)."""
import csv
import json
import os
from datetime import date
from pathlib import Path

# Путь относительно репозитория, не зависит от машины; переопределяется env AIZAK_DATASET.
DEFAULT_DATASET = Path(__file__).resolve().parent.parent / "data" / "hackathon-dataset-anonymized.csv"

REQUIRED_FIELDS = (
    "id", "anon_name", "categories", "city", "price_from_kzt",
    "event_formats", "languages", "busy_dates",
)
LIST_FIELDS = ("categories", "event_formats", "languages", "busy_dates")
BOOL_FIELDS = ("synthetic", "city_imputed", "price_imputed")


def _to_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split("|") if v.strip()]


def _to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def normalize_profile(raw: dict, line_no: int | None = None) -> dict:
    """Приводит сырую запись к типизированному профилю. Бросает ValueError при ошибке."""
    where = f"строка {line_no}" if line_no else f"id={raw.get('id')}"
    # busy_dates может быть пустым (свободен весь период), но поле должно присутствовать
    missing = [f for f in REQUIRED_FIELDS
               if f not in raw or (raw[f] in (None, "") and f != "busy_dates")]
    if missing:
        raise ValueError(f"{where}: нет обязательных полей {missing}")

    p = dict(raw)
    for f in LIST_FIELDS:
        p[f] = _to_list(raw.get(f))
    for f in BOOL_FIELDS:
        p[f] = _to_bool(raw.get(f, False))

    try:
        p["price_from_kzt"] = int(float(raw["price_from_kzt"]))
    except (TypeError, ValueError):
        raise ValueError(f"{where}: price_from_kzt не число: {raw['price_from_kzt']!r}")

    mh = raw.get("max_hours")
    p["max_hours"] = None if mh in (None, "") else int(float(mh))

    for d in p["busy_dates"]:
        try:
            date.fromisoformat(d)
        except ValueError:
            raise ValueError(f"{where}: некорректная дата в busy_dates: {d!r}")

    p["id"] = str(p["id"]).strip()
    p["city"] = str(p["city"]).strip()
    p["description"] = (raw.get("description") or "").strip()
    return p


def load_profiles(path: str | Path | None = None) -> list[dict]:
    """Читает .jsonl или .csv и возвращает список валидных профилей."""
    path = Path(path or os.environ.get("AIZAK_DATASET") or DEFAULT_DATASET)
    if path.suffix == ".jsonl":
        rows = [
            (i, json.loads(line))
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if line.strip()
        ]
    else:
        with path.open(encoding="utf-8", newline="") as fh:
            rows = list(enumerate(csv.DictReader(fh), 2))

    profiles = [normalize_profile(r, i) for i, r in rows]
    ids = [p["id"] for p in profiles]
    if len(ids) != len(set(ids)):
        raise ValueError("в датасете есть повторяющиеся id")
    return profiles
