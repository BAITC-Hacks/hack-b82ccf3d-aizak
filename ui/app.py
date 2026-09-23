"""Run from the repository root: python -m streamlit run ui/app.py."""
from datetime import date, timedelta
import streamlit as st

from catalog import REASON_LABELS
from contracts import BackendError, ContractError, RequestError
from service import get_search_service


def format_kzt(value):
    return f"{value:,}".replace(",", " ") + " ₸"


st.set_page_config(page_title="AIZAK — подбор подрядчиков", page_icon="✦", layout="wide")
try:
    service = get_search_service()
except BackendError as exc:
    for key in ("result", "last_request", "search_error", "result_source"):
        st.session_state.pop(key, None)
    st.title("AIZAK")
    st.error(str(exc))
    st.stop()
result_source = ("matching-contract-v2-explanations", service.is_demo)
if st.session_state.get("result_source") != result_source:
    for key in ("result", "last_request", "search_error"):
        st.session_state.pop(key, None)
    st.session_state["result_source"] = result_source
st.caption("AIZAK / HACKALEM")
st.title("AIZAK")
st.markdown("### Команда для вашего события")
st.write("Расскажите о мероприятии — подберём до трёх подрядчиков и объясним каждый выбор.")
if service.is_demo:
    st.info("Демонстрационный режим. Все профили и цены вымышлены; реальный конкурсный датасет не используется.")

if any(not service.catalog.get(key) for key in ("city", "category", "event_type")):
    st.warning("Каталог пока пуст. Подрядчики появятся после загрузки данных.")
    st.stop()

with st.form("contractor_search"):
    st.subheader("Ваше мероприятие")
    first, second, third = st.columns(3)
    with first:
        city = st.selectbox("Город", service.catalog["city"], key="city")
        event_type = st.selectbox("Формат мероприятия", service.catalog["event_type"], format_func=str.capitalize, key="event_type")
    with second:
        category = st.selectbox("Категория подрядчика", service.catalog["category"], key="category")
        default_date = min(max(date.today() + timedelta(days=1), service.calendar_start), service.calendar_end)
        event_date = st.date_input(
            "Дата мероприятия", value=default_date, min_value=service.calendar_start,
            max_value=service.calendar_end, format="DD.MM.YYYY", key="date",
        )
    with third:
        budget = st.number_input("Бюджет, ₸", min_value=1, value=200000, step=10000, key="budget")
        st.caption("Бюджет на одного подрядчика. Цена «от»; окончательная стоимость уточняется отдельно.")
    st.caption(f"Окно календаря: {service.calendar_start:%d.%m.%Y}–{service.calendar_end:%d.%m.%Y}. Доступность по данным не гарантирует бронирование.")
    with st.expander("Дополнительные условия"):
        left, right = st.columns(2)
        language = left.selectbox("Язык", [None, *service.catalog.get("language", ())], format_func=lambda value: value.capitalize() if value else "Не важно", key="language")
        hours = right.number_input("Длительность, ч", min_value=0, value=0, step=1, help="0 — без ограничения по длительности.", key="hours")
    submitted = st.form_submit_button("Подобрать", type="primary", use_container_width=True)

if submitted:
    request = {
        "city": city, "category": category, "date": event_date.isoformat(),
        "event_type": event_type, "budget": budget, "language": language, "hours": hours or None,
    }
    # Failed searches must not leave cards from an earlier successful request.
    for key in ("result", "last_request", "search_error"):
        st.session_state.pop(key, None)
    try:
        with st.spinner("Подбираем подрядчиков…"):
            st.session_state["result"] = service.search(request)
        st.session_state["last_request"] = request
    except (RequestError, ContractError, BackendError) as exc:
        st.session_state["search_error"] = str(exc)

if st.session_state.get("search_error"):
    st.error(st.session_state["search_error"])

result = st.session_state.get("result")
if result is None:
    if not st.session_state.get("search_error"):
        st.caption("Заполните форму и нажмите «Подобрать».")
else:
    st.divider()
    st.subheader("Результаты подбора")
    query = st.session_state["last_request"]
    st.caption(f"{query['city']} · {query['category']} · {date.fromisoformat(query['date']):%d.%m.%Y}")
    st.caption("Результаты относятся к последнему выполненному поиску. После изменения условий нажмите «Подобрать».")
    if result["status"] == "no_category":
        st.warning("В выбранном городе нет такой категории подрядчиков.")
    elif result["status"] == "none_match":
        st.warning("Подходящих подрядчиков нет: категория есть, но никто не прошёл заданные условия.")
    else:
        st.success(f"Подобрано подрядчиков: {len(result['matches'])} из максимум 3.")
    st.write(result["message"])
    if result.get("explanation_status") in ("configuration_error", "api_unavailable", "invalid_response"):
        st.caption("AI-объяснения сейчас недоступны. Показаны объяснения по данным каталога.")
    for column, match in zip(st.columns(len(result["matches"]) or 1), result["matches"]):
        profile = match["profile"]
        with column, st.container(border=True):
            if service.is_demo:
                st.caption("ТЕСТОВЫЙ ПРОФИЛЬ")
            elif profile["synthetic"]:
                st.caption("СИНТЕТИЧЕСКИЙ ПРОФИЛЬ")
            st.subheader(profile["anon_name"])
            st.write(f"{profile['city']} · {', '.join(profile['categories'])}")
            st.metric("Стартовая цена", "от " + format_kzt(profile["price_from_kzt"]))
            st.markdown("**Почему подходит**")
            st.write(match.get("explanation") or " ".join(match["match_reasons"][:2]))
            if match.get("explanation_source"):
                st.caption("Объяснение: OpenAI" if match["explanation_source"] == "openai"
                           else "Объяснение по данным каталога")
            if len(match["match_reasons"]) > 2:
                with st.expander("Все причины соответствия"):
                    for reason in match["match_reasons"]:
                        st.write("• " + reason)
            warnings = list(match["warnings"])
            if profile["price_imputed"]:
                warnings.append("Цена восстановлена при подготовке данных — уточните её.")
            if profile["city_imputed"]:
                warnings.append("Город восстановлен при подготовке данных — уточните его.")
            for warning in dict.fromkeys(warnings):
                st.caption(warning)
    if result["more_available"]:
        st.caption(f"Показаны первые три. Подходят ещё: {result['more_available']}.")
    if result["excluded"]:
        with st.expander(f"Почему не подошли остальные: {len(result['excluded'])}"):
            st.caption("У одного подрядчика может быть несколько причин исключения.")
            for item in result["excluded"]:
                reasons = "; ".join(REASON_LABELS.get(code, "другое условие заказа") for code in item["reasons"])
                st.write(f"{item['name']}: {reasons}.")
