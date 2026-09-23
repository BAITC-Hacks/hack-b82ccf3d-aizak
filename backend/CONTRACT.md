# Контракт подбора подрядчиков (v1)

Изменения контракта — только с уведомлением команды.

```python
from loader import load_profiles
from matching import find_contractors
result = find_contractors(request, load_profiles())
```

## request
| поле | тип | обяз. | пример |
|---|---|---|---|
| city | str | да | `"Алматы"` |
| date | str YYYY-MM-DD | да | `"2026-11-14"` |
| event_type | str | да | `"свадьба"` |
| category | str | да | `"Фотограф"` |
| budget | int, ₸ | да | `500000` |
| hours | int \| null | нет | `6` |
| language | str \| null | нет | `"казахский"` |

Невалидный запрос → `ValueError` с текстом ошибки.

## response
```json
{
  "status": "found | no_category | none_match",
  "message": "Подобрано 2 из 3: всего кандидатов 8, остальные отсеяны (занят на эту дату — 5; ...)",
  "matches": [
    {"id": "HK-…", "profile": {…все поля датасета…},
     "match_reasons": ["Цена от 300 000 ₸ при бюджете 500 000 ₸ — запас 40%.", "..."],
     "warnings": ["Синтетический профиль (не реальный подрядчик)."]}
  ],
  "excluded": [{"id": "HK-…", "name": "…", "reasons": ["busy_date", "over_budget"]}],
  "more_available": 0,
  "funnel": {"in_city_category": 8, "rejected_busy_date": 5, "passed": 2}
}
```

- `status`: `found` — есть карточки (1–3); `no_category` — в городе нет такой категории; `none_match` — кандидаты есть, но никто не прошёл условия.
- `message` показывать всегда — это объяснение пустой/неполной выдачи.
- `matches` — максимум 3, сортировка: `price_from_kzt` ↑, затем `id` ↑.
- `excluded` — только кандидаты нужного города и категории; все причины, не только первая.
- Коды причин (`REASON_TEXT` в `matching.py`): `date_outside_calendar`, `busy_date`, `over_budget`, `format_mismatch`, `hours_exceeded`, `language_mismatch`.

## Правила фильтров
- Город, категория, формат, язык — сравнение без учёта регистра.
- Бюджет: `price_from_kzt <= budget`.
- Длительность: `max_hours = null` (флорист, декоратор, сувениры) — не ограничивает; иначе `max_hours >= hours`.
- Дата вне окна календаря 23.09.2026–31.12.2026 — доступность неизвестна, подрядчик не считается свободным.
