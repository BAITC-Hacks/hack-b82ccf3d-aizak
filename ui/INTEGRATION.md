# AIZAK interface

Run from the repository root with Python 3.12:

```powershell
python -m pip install -r ui/requirements.txt
python -m streamlit run ui/app.py
python -m unittest discover -s ui/tests -v
```

The UI currently uses only explicitly fictional records from `ui/mock_data.py`.
It does not load, alter or impersonate the competition dataset.

The official case text has not yet been supplied. The initial form follows the
frontend task and the observed contract in `backend/matching.py` and
`backend/loader.py`, branch `feature/matching`, commit `3220b61`. This is an
observed implementation, not a claim of an agreed or final API contract.

Request fields: `city`, `category`, `date` (ISO YYYY-MM-DD), `event_type`,
`budget` (integer KZT), `language` (string or null), `hours` (integer or null).

Response: `matches` (at most 3 objects with `id`, `profile`, `match_reasons`,
optional `warnings`), `excluded`; optional `status`, `message`, `more_available`.
Cards currently read `profile.anon_name`, `city`, `categories`, `price_from_kzt`.

Before connecting actual results, confirm the final contract, catalogue values
for cities/categories/formats/languages, and the backend entry point or API URL
with Alibek. Replace the demo provider at the import/call in `ui/app.py` with an
adapter. Remove the unconditional demo labels only when an actual data source
is connected, preserving per-profile synthetic-data warnings. Add handling for
network failures if an HTTP service is used. Do not silently fall back to mock
results when a real backend fails.

Demo examples: Astana / host / 200000 KZT returns three cards; a 1 KZT budget
returns no results; Almaty / photographer returns one. The date 2030-01-15 is
marked busy in all fictional profiles. Optional duration above 8 hours excludes
the corresponding demo profiles.
