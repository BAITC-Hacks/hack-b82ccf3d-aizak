"""Run from the repository root: python -m streamlit run ui/app.py."""

from datetime import date, timedelta

import streamlit as st

from mock_data import CATEGORIES, CITIES, EVENT_TYPES, LANGUAGES, format_kzt, search_contractors


st.set_page_config(page_title="AIZAK — подбор подрядчиков", page_icon="✦", layout="wide")
st.caption("AIZAK / HACKALEM")
st.title("AIZAK")
st.markdown("### Команда для вашего события")
st.write("Расскажите о мероприятии — подберём до трёх подрядчиков и объясним каждый выбор.")
st.info("Демонстрационный режим. Все профили и цены вымышлены; реальный конкурсный датасет не используется.")

with st.form("contractor_search"):
    st.subheader("Ваше мероприятие")
    first, second, third = st.columns(3)
    with first:
        city = st.selectbox("Город", CITIES, key="city")
        event_type = st.selectbox("Формат мероприятия", EVENT_TYPES, key="event_type")
    with second:
        category = st.selectbox("Категория подрядчика", CATEGORIES, key="category")
        event_date = st.date_input(
            "Дата мероприятия", value=date.today() + timedelta(days=1),
            min_value=date.today(), format="DD.MM.YYYY", key="date",
        )
    with third:
        budget = st.number_input("Бюджет, ₸", min_value=1, value=200000, step=10000, key="budget")
        st.caption("Бюджет на одного подрядчика. Итоговая стоимость уточняется отдельно.")
    with st.expander("Дополнительные условия"):
        left, right = st.columns(2)
        language = left.selectbox("Язык", ["Не важно", *LANGUAGES], key="language")
        hours = right.number_input(
            "Длительность, ч", min_value=0, max_value=24, value=0, step=1,
            help="0 — без ограничения по длительности.", key="hours",
        )
    submitted = st.form_submit_button("Подобрать", type="primary", use_container_width=True)

if submitted:
    request = {
        "city": city, "category": category, "date": event_date.isoformat(),
        "event_type": event_type, "budget": budget,
        "language": None if language == "Не важно" else language,
        "hours": hours or None,
    }
    try:
        st.session_state["result"] = search_contractors(request)
        st.session_state["last_request"] = request
    except ValueError as exc:
        st.session_state.pop("result", None)
        st.error(str(exc))

result = st.session_state.get("result")
if result is None:
    st.caption("Заполните форму и нажмите «Подобрать». Для примера: Астана, ведущий, бюджет 200 000 ₸.")
else:
    st.divider()
    st.subheader("Результаты подбора")
    query = st.session_state["last_request"]
    st.caption(f"{query['city']} · {query['category']} · {date.fromisoformat(query['date']):%d.%m.%Y}")
    matches = result.get("matches", [])[:3]
    if not matches:
        st.warning("Подходящих подрядчиков нет. Попробуйте другой город, дату или увеличьте бюджет.")
    else:
        for column, match in zip(st.columns(len(matches)), matches):
            profile = match["profile"]
            with column, st.container(border=True):
                st.caption("ТЕСТОВЫЙ ПРОФИЛЬ")
                st.subheader(profile["anon_name"])
                st.write(f"{profile['city']} · {', '.join(profile['categories'])}")
                st.metric("Стартовая цена", "от " + format_kzt(profile["price_from_kzt"]))
                st.markdown("**Почему подходит**")
                for reason in match.get("match_reasons", []):
                    st.write("• " + reason)
                for warning in match.get("warnings", []):
                    st.caption(warning)
        if result.get("more_available", 0):
            st.caption(f"Показаны первые три. В тестовом наборе подходят ещё: {result['more_available']}.")
    if result.get("excluded"):
        st.caption(f"Не прошли условия в выбранном городе и категории: {len(result['excluded'])}.")
