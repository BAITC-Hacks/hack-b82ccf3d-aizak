# Контракт подбора подрядчиков (v1)

Изменения контракта — только с уведомлением команды.

```python
# из корня репозитория (или добавив корень в sys.path)
from backend import find_contractors, load_profiles
result = find_contractors(request, load_profiles())
```

Датасет по умолчанию — `data/hackathon-dataset-anonymized.csv` (путь от репозитория).
Другой файл (в т.ч. официальный `.jsonl`) — `load_profiles(path)` или env `AIZAK_DATASET`.
Backend — только стандартная библиотека Python 3.10+, зависимостей нет.

### Подключение в Streamlit (`ui/service.py`)
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # корень репо
from backend import find_contractors, load_profiles

def get_search_service():
    return make_backend_service(find_contractors, load_profiles())
```
`backend` — пакет, чтобы его модули не конфликтовали с `ui/service.py` и `ui/contracts.py`.

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

`hours` / `language` можно передавать как `None`. Невалидный запрос → `ValueError` с текстом ошибки.

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

## Дополнительный слой объяснений (интеграционная версия)

`find_contractors` и его контракт выше не изменены. После него UI может вызвать
`backend.explanations.add_explanations(request, result)`. Функция возвращает копию,
добавляя только `explanation` и `explanation_source` к выбранным карточкам и
`explanation_status` к непустому результату. ID и порядок, профили, match_reasons,
warnings, excluded, funnel и more_available сохраняются.

Провайдер OpenAI настраивается через `OPENAI_API_KEY` в окружении либо `backend/.env`.
Пример без секретов — `backend/.env.example`. При недоступном AI остаются объяснения
по подтверждённым полям каталога. Прямые вызовы `find_contractors` никогда не вызывают API.
