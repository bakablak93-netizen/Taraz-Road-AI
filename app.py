
import csv
import io
import inspect
import os
import uuid
from datetime import datetime

import pandas as pd
import streamlit as st
import folium

from services.database import (
    init_db,
    add_report,
    list_reports,
    get_report,
    update_status,
    add_vote,
    add_comment,
    list_comments,
    list_status_history,
    save_after_photo,
    delete_report,
)


# ============================================================
# НАСТРОЙКИ
# ============================================================

st.set_page_config(
    page_title="Taraz Road AI",
    page_icon="🛣️",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

if "voter_token" not in st.session_state:
    st.session_state.voter_token = str(uuid.uuid4())

if "upload_version" not in st.session_state:
    st.session_state.upload_version = 0


ISSUE_TYPES = [
    "Яма на дороге",
    "Трещины на дороге",
    "Повреждение тротуара",
    "Проблема с люком",
    "Дорожный знак",
    "Светофор",
    "Уличное освещение",
    "Дорожная разметка",
    "Другая проблема",
]

STATUSES = [
    "Новая",
    "На рассмотрении",
    "В работе",
    "Исправлено",
    "Отклонено",
]

STATUS_COLORS = {
    "Новая": "#e67e22",
    "На рассмотрении": "#3498db",
    "В работе": "#8e44ad",
    "Исправлено": "#27ae60",
    "Отклонено": "#7f8c8d",
}


# ============================================================
# СТИЛЬ
# ============================================================

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }

    .hero {
        padding: 24px;
        border-radius: 18px;
        background: linear-gradient(120deg, #143b66, #177a89);
        color: white;
        margin-bottom: 20px;
    }

    .hero h1 {
        color: white;
        margin: 0;
        font-size: 2.1rem;
    }

    .hero p {
        margin: 10px 0 0 0;
        font-size: 1rem;
        opacity: 0.95;
    }

    .report-title {
        font-size: 1.15rem;
        font-weight: 700;
        margin-bottom: 5px;
    }

    .muted {
        color: #888;
        font-size: 0.88rem;
    }

    div[data-testid="stMetric"] {
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 12px;
        padding: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def as_dict(item):
    """Преобразует запись SQLite или словарь в обычный dict."""
    if item is None:
        return {}

    if isinstance(item, dict):
        return item

    try:
        return dict(item)
    except Exception:
        return {}


def call_database(func, **values):
    """
    Передаёт только те аргументы, которые поддерживает функция.
    Это помогает сохранить совместимость с database.py.
    """
    signature = inspect.signature(func)
    parameters = signature.parameters

    if any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in parameters.values()
    ):
        return func(**values)

    accepted = {
        name: value
        for name, value in values.items()
        if name in parameters
    }

    return func(**accepted)


def load_reports(sort_by="priority"):
    try:
        data = list_reports(sort_by=sort_by)
    except TypeError:
        data = list_reports()

    reports = [as_dict(item) for item in data]

    if sort_by == "newest":
        reports.sort(
            key=lambda x: str(x.get("created_at") or ""),
            reverse=True,
        )
    elif sort_by == "popular":
        reports.sort(
            key=lambda x: int(x.get("votes_count") or 0),
            reverse=True,
        )
    else:
        reports.sort(
            key=lambda x: (
                float(x.get("priority_score") or 0),
                int(x.get("votes_count") or 0),
            ),
            reverse=True,
        )

    return reports


def get_report_safe(report_id):
    try:
        result = get_report(int(report_id))
        return as_dict(result)
    except Exception:
        for report in load_reports():
            if int(report.get("id") or 0) == int(report_id):
                return report

    return {}


def image_bytes(uploaded_file):
    if uploaded_file is None:
        return None
    return uploaded_file.getvalue()


def display_image(path, caption=None):
    if not path:
        return

    if os.path.exists(str(path)):
        st.image(str(path), caption=caption, use_container_width=True)


def status_badge(status):
    color = STATUS_COLORS.get(status, "#64748b")

    st.markdown(
        f"""
        <span style="
            background:{color};
            color:white;
            padding:5px 11px;
            border-radius:20px;
            font-size:13px;
            font-weight:600;
        ">{status}</span>
        """,
        unsafe_allow_html=True,
    )


def format_date(value):
    if not value:
        return "Дата не указана"

    return str(value).replace("T", " ")[:16]


def calculate_priority(severity, confidence=0.75):
    """Предварительный балл срочности от 0 до 100."""
    score = severity * 8 + confidence * 20
    return round(min(100, max(0, score)), 1)


def priority_label(score, votes=0):
    score = float(score or 0)
    votes = int(votes or 0)

    adjusted = min(100, score + min(votes * 2, 20))

    if adjusted >= 75:
        return "🔴 Высокая"
    if adjusted >= 45:
        return "🟠 Средняя"
    return "🟢 Низкая"


def render_comments(report_id):
    st.markdown("**Комментарии жителей**")

    try:
        comments = list_comments(report_id)
    except Exception as exc:
        st.warning(f"Не удалось загрузить комментарии: {exc}")
        comments = []

    if not comments:
        st.caption("Пока нет комментариев.")

    for item in comments:
        comment = as_dict(item)

        author = (
            comment.get("author")
            or comment.get("author_name")
            or comment.get("name")
            or "Житель"
        )

        message = (
            comment.get("comment")
            or comment.get("text")
            or comment.get("content")
            or ""
        )

        date = format_date(comment.get("created_at"))

        st.markdown(f"**{author}** · {date}")
        st.write(message)

    with st.form(f"comment_form_{report_id}", clear_on_submit=True):
        author = st.text_input(
            "Ваше имя",
            value="Житель Тараза",
            key=f"author_{report_id}",
        )

        message = st.text_area(
            "Ваш комментарий",
            max_chars=500,
            key=f"message_{report_id}",
        )

        submitted = st.form_submit_button("Отправить комментарий")

        if submitted:
            if not message.strip():
                st.warning("Напишите комментарий.")
            else:
                try:
                    call_database(
                        add_comment,
                        report_id=report_id,
                        author=author.strip() or "Житель",
                        author_name=author.strip() or "Житель",
                        name=author.strip() or "Житель",
                        comment=message.strip(),
                        text=message.strip(),
                        content=message.strip(),
                    )

                    st.success("Комментарий добавлен.")
                    st.rerun()

                except Exception as exc:
                    st.error(f"Ошибка добавления комментария: {exc}")


def render_history(report_id):
    try:
        history = list_status_history(report_id)
    except Exception:
        history = []

    if not history:
        st.caption("История изменений пока пуста.")
        return

    for item in history:
        event = as_dict(item)

        old_status = event.get("old_status") or "—"
        new_status = event.get("new_status") or event.get("status") or "—"
        date = format_date(event.get("created_at"))

        st.write(f"🕒 {date}: {old_status} → **{new_status}**")


def render_report_card(report, show_comments=True):
    report_id = report.get("id")
    issue = report.get("defect_type") or "Проблема на дороге"
    address = report.get("address") or "Адрес не указан"
    status = report.get("status") or "Новая"
    votes = int(report.get("votes_count") or 0)
    score = float(report.get("priority_score") or 0)

    with st.container(border=True):
        col_photo, col_info = st.columns([1, 2], gap="large")

        with col_photo:
            path = report.get("image_path")

            if path and os.path.exists(str(path)):
                st.image(str(path), use_container_width=True)
            else:
                st.info("📷 Фото недоступно")

            after_path = report.get("after_image_path")

            if after_path and os.path.exists(str(after_path)):
                with st.expander("Фото после ремонта"):
                    st.image(str(after_path), use_container_width=True)

        with col_info:
            st.markdown(f"### #{report_id} · {issue}")

            st.write(f"📍 {address}")
            st.caption(f"📅 {format_date(report.get('created_at'))}")

            status_badge(status)

            st.write("")
            st.write(f"**Приоритет:** {priority_label(score, votes)}")
            st.write(f"**Поддержали:** {votes} человек")

            if st.button(
                f"👍 Поддержать ({votes})",
                key=f"vote_{report_id}",
            ):
                try:
                    result = call_database(
                        add_vote,
                        report_id=report_id,
                        voter_token=st.session_state.voter_token,
                        voter_id=st.session_state.voter_token,
                        token=st.session_state.voter_token,
                    )

                    if result is False:
                        st.info("Вы уже поддержали это обращение.")
                    else:
                        st.success("Ваш голос учтён!")

                    st.rerun()

                except Exception as exc:
                    st.warning(f"Не удалось проголосовать: {exc}")

        if show_comments:
            with st.expander(
                f"💬 Комментарии · обращение #{report_id}"
            ):
                render_comments(report_id)

        with st.expander("📋 История обращения"):
            render_history(report_id)


# ============================================================
# БОКОВАЯ ПАНЕЛЬ
# ============================================================

with st.sidebar:
    st.markdown("## 🛣️ Taraz Road AI")
    st.caption("Умный город начинается с жителей")

    st.divider()

    st.write("**Как это работает?**")
    st.write("1. Сообщите о проблеме.")
    st.write("2. Укажите место и добавьте фото.")
    st.write("3. Жители смогут поддержать обращение.")
    st.write("4. Следите за статусом решения.")

    st.divider()

    st.caption("Прототип для Digital Taraz Hackathon")
    st.caption("Город Тараз, Казахстан 🇰🇿")


# ============================================================
# ЗАГОЛОВОК
# ============================================================

st.markdown(
    """
    <div class="hero">
        <h1>🛣️ Taraz Road AI</h1>
        <p>
            Сообщайте о проблемах дорог, поддерживайте обращения
            и следите за их решением.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)


reports = load_reports()

total_reports = len(reports)

completed_reports = sum(
    1
    for report in reports
    if report.get("status") == "Исправлено"
)

active_reports = sum(
    1
    for report in reports
    if report.get("status") in (
        "Новая",
        "На рассмотрении",
        "В работе",
    )
)

total_votes = sum(
    int(report.get("votes_count") or 0)
    for report in reports
)

m1, m2, m3, m4 = st.columns(4)

m1.metric("Всего обращений", total_reports)
m2.metric("Активные", active_reports)
m3.metric("Исправлено", completed_reports)
m4.metric("Голосов жителей", total_votes)

st.write("")


# ============================================================
# ВКЛАДКИ
# ============================================================

tab_new, tab_feed, tab_map, tab_track, tab_admin = st.tabs(
    [
        "➕ Новое обращение",
        "📰 Лента проблем",
        "🗺️ Карта",
        "🔎 Проверить статус",
        "🛠️ Администратор",
    ]
)


# ============================================================
# 1. НОВОЕ ОБРАЩЕНИЕ
# ============================================================

with tab_new:
    st.subheader("Сообщить о проблеме")

    st.write(
        "Сфотографируйте проблему или выберите снимок "
        "из галереи телефона."
    )

    with st.form(
        f"new_report_form_{st.session_state.upload_version}"
    ):
        uploaded_image = st.file_uploader(
            "📷 Фотография проблемы",
            type=["jpg", "jpeg", "png"],
            help="Можно выбрать фотографию с телефона или компьютера.",
        )

        issue_type = st.selectbox(
            "Тип проблемы",
            ISSUE_TYPES,
        )

        address = st.text_input(
            "📍 Адрес или ориентир",
            placeholder="Например: Тараз, проспект Абая, возле остановки",
        )

        st.caption(
            "Координаты необязательны. "
            "Если знаете точку на карте, укажите её ниже."
        )

        col_lat, col_lon = st.columns(2)

        with col_lat:
            latitude = st.number_input(
                "Широта",
                min_value=-90.0,
                max_value=90.0,
                value=42.9000,
                format="%.6f",
            )

        with col_lon:
            longitude = st.number_input(
                "Долгота",
                min_value=-180.0,
                max_value=180.0,
                value=71.3667,
                format="%.6f",
            )

        severity = st.slider(
            "Насколько серьёзная проблема?",
            min_value=1,
            max_value=10,
            value=5,
            help="1 — небольшая проблема, 10 — опасная ситуация.",
        )

        st.write("**Насколько опасна эта проблема?**")

        danger = st.radio(
            "Оценка опасности",
            [
                "Не очень опасно",
                "Мешает движению",
                "Может привести к аварии",
            ],
            horizontal=True,
        )

        confirmed = st.checkbox(
            "Я подтверждаю, что информация соответствует действительности."
        )

        submit_report = st.form_submit_button(
            "🚀 Отправить обращение",
            type="primary",
            use_container_width=True,
        )

    if submit_report:
        if uploaded_image is None:
            st.error("Добавьте фотографию проблемы.")

        elif not address.strip():
            st.error("Укажите адрес или ориентир.")

        elif not confirmed:
            st.error("Подтвердите достоверность информации.")

        else:
            try:
                image_data = image_bytes(uploaded_image)

                adjusted_severity = severity

                if danger == "Мешает движению":
                    adjusted_severity = min(10, severity + 1)
                elif danger == "Может привести к аварии":
                    adjusted_severity = min(10, severity + 2)

                confidence = 0.75

                score = calculate_priority(
                    adjusted_severity,
                    confidence,
                )

                result = call_database(
                    add_report,
                    image_bytes=image_data,
                    image_data=image_data,
                    image=image_data,
                    uploaded_file=image_data,
                    filename=uploaded_image.name,
                    image_name=uploaded_image.name,
                    defect_type=issue_type,
                    confidence=confidence,
                    latitude=latitude,
                    longitude=longitude,
                    address=address.strip(),
                    severity=adjusted_severity,
                    priority_score=score,
                    mode="manual",
                )

                if result is False:
                    st.warning(
                        "Похожее обращение уже было отправлено недавно."
                    )
                else:
                    st.success(
                        "Обращение отправлено! "
                        "Теперь оно появится в общей ленте."
                    )
                    st.balloons()

                    st.session_state.upload_version += 1

            except Exception as exc:
                st.error(f"Не удалось сохранить обращение: {exc}")

    st.info(
        "ℹ️ Сейчас тип проблемы выбирается вручную. "
        "Автоматическое распознавание появится при подключении "
        "обученной модели road_damage.pt."
    )


# ============================================================
# 2. ЛЕНТА ПРОБЛЕМ
# ============================================================

with tab_feed:
    st.subheader("Проблемы, о которых сообщили жители")

    filter_col, sort_col, search_col = st.columns([1, 1, 2])

    with filter_col:
        status_filter = st.selectbox(
            "Статус",
            ["Все"] + STATUSES,
            key="feed_status_filter",
        )

    with sort_col:
        sort_label = st.selectbox(
            "Сортировка",
            [
                "Сначала срочные",
                "Сначала новые",
                "Самые популярные",
            ],
        )

    with search_col:
        search_query = st.text_input(
            "Поиск",
            placeholder="Адрес, тип проблемы или номер",
        )

    sort_values = {
        "Сначала срочные": "priority",
        "Сначала новые": "newest",
        "Самые популярные": "popular",
    }

    filtered_reports = load_reports(
        sort_values[sort_label]
    )

    if status_filter != "Все":
        filtered_reports = [
            report
            for report in filtered_reports
            if report.get("status") == status_filter
        ]

    if search_query.strip():
        query = search_query.lower().strip()

        filtered_reports = [
            report
            for report in filtered_reports
            if (
                query in str(report.get("id") or "").lower()
                or query in str(report.get("address") or "").lower()
                or query in str(report.get("defect_type") or "").lower()
            )
        ]

    st.caption(
        f"Найдено обращений: {len(filtered_reports)}"
    )

    if not filtered_reports:
        st.info("По вашему запросу обращений пока нет.")

    for report in filtered_reports:
        render_report_card(report)


# ============================================================
# 3. КАРТА ПРОБЛЕМ
# ============================================================

with tab_map:
    st.subheader("Карта дорожных проблем Тараза")

    st.caption(
        "Красный — высокая срочность, "
        "оранжевый — средняя, зелёный — низкая."
    )

    map_status = st.selectbox(
        "Показать на карте",
        ["Все"] + STATUSES,
        key="map_status_filter",
    )

    map_reports = load_reports()

    if map_status != "Все":
        map_reports = [
            report
            for report in map_reports
            if report.get("status") == map_status
        ]

    road_map = folium.Map(
        location=[42.9000, 71.3667],
        zoom_start=12,
        tiles="OpenStreetMap",
    )

    marker_count = 0

    for report in map_reports:
        lat = report.get("latitude")
        lon = report.get("longitude")

        if lat is None or lon is None:
            continue

        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            continue

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        score = float(report.get("priority_score") or 0)
        votes = int(report.get("votes_count") or 0)

        adjusted_score = min(100, score + min(votes * 2, 20))

        if adjusted_score >= 75:
            marker_color = "red"
        elif adjusted_score >= 45:
            marker_color = "orange"
        else:
            marker_color = "green"

        popup_text = (
            f"Обращение #{report.get('id')}\n"
            f"{report.get('defect_type')}\n"
            f"{report.get('address')}\n"
            f"Статус: {report.get('status')}\n"
            f"Поддержали: {votes}"
        )

        folium.Marker(
            location=[lat, lon],
            tooltip=f"Обращение #{report.get('id')}",
            popup=folium.Popup(
                popup_text.replace("\n", "<br>"),
                max_width=300,
            ),
            icon=folium.Icon(
                color=marker_color,
                icon="info-sign",
            ),
        ).add_to(road_map)

        marker_count += 1

    st.components.v1.html(
        road_map._repr_html_(),
        height=540,
        scrolling=False,
    )

    st.caption(f"На карте отмечено: {marker_count}")


# ============================================================
# 4. ПРОВЕРКА СТАТУСА
# ============================================================

with tab_track:
    st.subheader("Проверить статус обращения")

    st.write(
        "Введите номер обращения, чтобы узнать, "
        "что с ним происходит."
    )

    report_number = st.number_input(
        "Номер обращения",
        min_value=1,
        step=1,
        value=1,
    )

    if st.button(
        "🔎 Найти обращение",
        type="primary",
    ):
        report = get_report_safe(report_number)

        if not report:
            st.warning("Обращение с таким номером не найдено.")
        else:
            st.session_state.tracked_report_id = int(report_number)

    tracked_id = st.session_state.get("tracked_report_id")

    if tracked_id:
        tracked_report = get_report_safe(tracked_id)

        if tracked_report:
            render_report_card(tracked_report)


# ============================================================
# 5. ПАНЕЛЬ АДМИНИСТРАТОРА
# ============================================================

with tab_admin:
    st.subheader("Панель администратора")

    st.warning(
        "⚠️ Демонстрационный режим: пока нет авторизации. "
        "Для реального запуска доступ к этому разделу "
        "необходимо защитить."
    )

    admin_reports = load_reports()

    st.markdown("### 📊 Статистика")

    if admin_reports:
        status_counts = pd.DataFrame(
            [
                {
                    "Статус": report.get("status") or "Новая",
                    "Количество": 1,
                }
                for report in admin_reports
            ]
        )

        status_counts = (
            status_counts
            .groupby("Статус", as_index=False)["Количество"]
            .sum()
        )

        st.bar_chart(
            status_counts.set_index("Статус")
        )

        type_counts = pd.DataFrame(
            [
                {
                    "Тип": report.get("defect_type") or "Другое",
                    "Количество": 1,
                }
                for report in admin_reports
            ]
        )

        type_counts = (
            type_counts
            .groupby("Тип", as_index=False)["Количество"]
            .sum()
        )

        with st.expander("Статистика по типам проблем"):
            st.bar_chart(
                type_counts.set_index("Тип")
            )

    else:
        st.info("Пока нет данных для статистики.")

    st.divider()

    st.markdown("### 📁 Экспорт обращений")

    if admin_reports:
        export_rows = []

        for report in admin_reports:
            export_rows.append(
                {
                    "ID": report.get("id"),
                    "Тип": report.get("defect_type"),
                    "Адрес": report.get("address"),
                    "Широта": report.get("latitude"),
                    "Долгота": report.get("longitude"),
                    "Серьёзность": report.get("severity"),
                    "Приоритет": report.get("priority_score"),
                    "Статус": report.get("status"),
                    "Голоса": report.get("votes_count", 0),
                    "Комментарии": report.get("comments_count", 0),
                    "Дата": report.get("created_at"),
                }
            )

        export_df = pd.DataFrame(export_rows)

        csv_data = export_df.to_csv(
            index=False,
        ).encode("utf-8-sig")

        st.download_button(
            "⬇️ Скачать CSV",
            data=csv_data,
            file_name="taraz_road_reports.csv",
            mime="text/csv",
        )

    st.divider()

    st.markdown("### 🛠️ Управление обращениями")

    if not admin_reports:
        st.info("Обращений пока нет.")

    else:
        admin_search = st.text_input(
            "Найти обращение",
            placeholder="Введите номер или адрес",
            key="admin_search",
        )

        admin_status_filter = st.selectbox(
            "Фильтр по статусу",
            ["Все"] + STATUSES,
            key="admin_status",
        )

        filtered_admin = admin_reports

        if admin_status_filter != "Все":
            filtered_admin = [
                report
                for report in filtered_admin
                if report.get("status") == admin_status_filter
            ]

        if admin_search.strip():
            query = admin_search.lower().strip()

            filtered_admin = [
                report
                for report in filtered_admin
                if (
                    query in str(report.get("id") or "")
                    or query in str(report.get("address") or "").lower()
                )
            ]

        st.caption(
            f"Показано обращений: {len(filtered_admin)}"
        )

        for report in filtered_admin:
            report_id = report.get("id")

            with st.expander(
                f"#{report_id} · "
                f"{report.get('defect_type')} · "
                f"{report.get('status')}"
            ):
                col_photo, col_details = st.columns([1, 2])

                with col_photo:
                    display_image(
                        report.get("image_path"),
                        "Фото проблемы",
                    )

                    display_image(
                        report.get("after_image_path"),
                        "После ремонта",
                    )

                with col_details:
                    st.write(
                        f"**Адрес:** {report.get('address') or '—'}"
                    )

                    st.write(
                        f"**Приоритет:** "
                        f"{priority_label(report.get('priority_score'), report.get('votes_count'))}"
                    )

                    st.write(
                        f"**Поддержали:** "
                        f"{report.get('votes_count') or 0}"
                    )

                    current_status = (
                        report.get("status")
                        if report.get("status") in STATUSES
                        else "Новая"
                    )

                    selected_status = st.selectbox(
                        "Новый статус",
                        STATUSES,
                        index=STATUSES.index(current_status),
                        key=f"admin_status_{report_id}",
                    )

                    if st.button(
                        "💾 Сохранить статус",
                        key=f"save_status_{report_id}",
                    ):
                        try:
                            call_database(
                                update_status,
                                report_id=report_id,
                                status=selected_status,
                                new_status=selected_status,
                            )

                            st.success("Статус обновлён.")
                            st.rerun()

                        except Exception as exc:
                            st.error(
                                f"Ошибка обновления статуса: {exc}"
                            )

                st.markdown("**📷 Фото после ремонта**")

                after_image = st.file_uploader(
                    "Добавить фото выполненной работы",
                    type=["jpg", "jpeg", "png"],
                    key=f"after_photo_{report_id}",
                )

                if after_image is not None:
                    if st.button(
                        "Сохранить фото после ремонта",
                        key=f"save_after_{report_id}",
                    ):
                        try:
                            after_data = after_image.getvalue()

                            call_database(
                                save_after_photo,
                                report_id=report_id,
                                image_bytes=after_data,
                                image_data=after_data,
                                image=after_data,
                                filename=after_image.name,
                            )

                            st.success("Фото сохранено.")
                            st.rerun()

                        except Exception as exc:
                            st.error(
                                f"Не удалось сохранить фото: {exc}"
                            )

                with st.expander("История изменения статуса"):
                    render_history(report_id)

                st.divider()

                st.markdown("**🗑️ Удаление обращения**")

                confirm_delete = st.checkbox(
                    f"Подтверждаю удаление обращения #{report_id}",
                    key=f"confirm_delete_{report_id}",
                )

                if st.button(
                    "Удалить обращение",
                    key=f"delete_{report_id}",
                    disabled=not confirm_delete,
                ):
                    try:
                        call_database(
                            delete_report,
                            report_id=report_id,
                        )

                        st.success("Обращение удалено.")
                        st.rerun()

                    except Exception as exc:
                        st.error(
                            f"Не удалось удалить обращение: {exc}"
                        )


# ============================================================
# ПОДВАЛ
# ============================================================

st.divider()

st.caption(
    "Taraz Road AI · Digital Taraz Hackathon 2026 · "
    "Прототип цифровой платформы для жителей города Тараз"
)
