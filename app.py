
import hashlib
import os
import uuid
from io import BytesIO
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from PIL import Image, ImageOps
from streamlit_folium import st_folium
from streamlit_geolocation import streamlit_geolocation
import re
import hmac

from services.database import (
    init_db, add_report, list_reports, get_report, update_status,
    add_vote, add_comment, list_comments, list_status_history,
    save_after_photo, delete_report,
)
from services.detection import detect_road_damage


# ============================================================
# НАСТРОЙКИ
# ============================================================

st.set_page_config(
    page_title="Taraz Road AI",
    page_icon="🛣️",
    layout="wide",
)

init_db()


# ============================================================
# СОВРЕМЕННЫЙ ДИЗАЙН
# ============================================================

st.markdown("""
<style>
    .stApp {
        background:
            radial-gradient(
                ellipse at top right,
                rgba(19, 92, 116, 0.13),
                transparent 45%
            ),
            #0b1220;
    }

    .block-container {
        max-width: 1420px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    h1, h2, h3 {
        letter-spacing: -0.6px;
    }

    [data-testid="stSidebar"] {
        background: #111e31;
        border-right: 1px solid #24354d;
    }

    [data-testid="stMetric"] {
        background: #142238;
        border: 1px solid #263a54;
        border-radius: 16px;
        padding: 18px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.09);
    }

    [data-testid="stMetricValue"] {
        color: #65dbc0;
        font-size: 30px;
        font-weight: 700;
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 16px;
    }

    div.stButton > button {
        border-radius: 10px;
        font-weight: 600;
        transition: 0.2s ease;
    }

    div.stButton > button[kind="primary"] {
        background: #14a88b;
        color: white;
        border: none;
    }

    div.stButton > button[kind="primary"]:hover {
        background: #0e8a72;
        color: white;
    }

    [data-baseweb="tab-list"] {
        gap: 10px;
        margin-bottom: 18px;
    }

    button[data-baseweb="tab"] {
        border-radius: 10px 10px 0 0;
        padding: 12px 16px;
    }

    button[data-baseweb="tab"][aria-selected="true"] {
        color: #65dbc0;
    }

    [data-testid="stFileUploader"],
    [data-testid="stCameraInput"] {
        border-radius: 14px;
    }

    .taraz-hero {
        background: linear-gradient(
            120deg,
            #123e57,
            #116d70
        );
        padding: 30px;
        border-radius: 20px;
        margin-bottom: 22px;
        border: 1px solid #276e79;
    }

    .taraz-hero h1 {
        margin: 0;
        color: white;
        font-size: 32px;
    }

    .taraz-hero p {
        color: #d4f4ed;
        margin: 12px 0 0;
    }
</style>
""", unsafe_allow_html=True)


ISSUES = [
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
    "На проверке",
    "На рассмотрении",
    "В работе",
    "Исправлено",
    "Отклонено",
]

if "voter_token" not in st.session_state:
    st.session_state.voter_token = str(uuid.uuid4())

if "upload_key" not in st.session_state:
    st.session_state.upload_key = 0


# ============================================================
# ФУНКЦИИ РАБОТЫ С ФОТО
# ============================================================

def photo_bytes(upload):
    """Поворачиваем фото с телефона и сохраняем как JPEG."""

    image = Image.open(BytesIO(upload.getvalue()))

    image = ImageOps.exif_transpose(image).convert("RGB")

    image.thumbnail((1800, 1800))

    output = BytesIO()

    image.save(
        output,
        format="JPEG",
        quality=88,
    )

    return output.getvalue()


def detected_type(label):
    """Преобразуем название класса ИИ в тип проблемы."""

    label = str(label).lower()

    if (
        "яма" in label
        or "pothole" in label
        or "d40" in label
    ):
        return "Яма на дороге"

    if (
        "трещин" in label
        or "crack" in label
        or "d00" in label
        or "d10" in label
        or "d20" in label
    ):
        return "Трещины на дороге"

    return None


# ============================================================
# AI-АНАЛИЗ ФОТОГРАФИИ
# ============================================================

def ai_for_photo(data):
    """
    Анализируем фото только один раз.
    Повторный ввод адреса не запускает ИИ заново.
    """

    signature = hashlib.sha256(data).hexdigest()

    if st.session_state.get("ai_photo_hash") != signature:

        with st.spinner(
            "ИИ анализирует фотографию. "
            "Первый запуск может быть долгим..."
        ):
            result = detect_road_damage(data)

        st.session_state.ai_photo_hash = signature
        st.session_state.ai_result = result

        if result.get("mode") == "ai":
            suggestion = detected_type(result.get("label"))
        else:
            suggestion = None

        st.session_state.issue_type = (
            suggestion or "Другая проблема"
        )

        score = result.get("severity_score")

        st.session_state.issue_severity = max(
            1,
            min(10, int(score or 5)),
        )

    return st.session_state.ai_result


def show_ai(result, show_photo=False):
    """Показывает результаты анализа ИИ."""

    if result.get("mode") != "ai":

        st.info(
            "ИИ временно недоступен. "
            "Можно заполнить обращение вручную."
        )

        if result.get("error"):
            st.caption(str(result["error"]))

        return

    count = int(
        result.get("detections_count") or 0
    )

    if count == 0:

        st.info(
            "ИИ не обнаружил повреждений. "
            "Это не гарантирует отсутствие проблемы."
        )

        return

    st.success(
        "🤖 ИИ обнаружил: "
        + str(result.get("label", "Дефект"))
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Найдено",
        count,
    )

    c2.metric(
        "Уверенность",
        f"{float(result.get('confidence') or 0):.0%}",
    )

    c3.metric(
        "Визуальная оценка",
        f"{result.get('severity_score', '?')}/10",
    )

    st.caption(
        f"Охват рамками: "
        f"{result.get('coverage_percent', 0)}% изображения. "
        "Это не реальная площадь ямы "
        "и не точная оценка опасности."
    )

    if (
        show_photo
        and result.get("annotated_image") is not None
    ):

        st.image(
            result["annotated_image"],
            caption="Повреждения, отмеченные моделью",
        )


# ============================================================
# ФУНКЦИИ ОТОБРАЖЕНИЯ ОБРАЩЕНИЙ
# ============================================================

def show_photo(path, title="Фото"):

    if path and Path(str(path)).is_file():

        st.image(
            str(path),
            caption=title,
            width="stretch",
        )

    else:
        st.caption("Фотография недоступна")


def show_history(report_id):

    rows = list_status_history(report_id)

    if not rows:
        st.caption("Изменений пока нет")

    for row in rows:

        old = row.get("old_status") or "Создано"

        st.write(
            f"{row.get('changed_at', '')}: "
            f"{old} → {row.get('new_status', '')}"
        )


# ============================================================
# РЕЙТИНГ ПРОБЛЕМНЫХ ДОРОГ
# ============================================================

def road_name(address):
    """
    Пытается выделить улицу из введённого адреса.
    """

    address = " ".join(
        str(address or "").strip().split()
    )

    if not address:
        return "Адрес не указан"

    match = re.search(
        r"(?:улица|ул\.?|проспект|пр-т|шоссе|"
        r"переулок|бульвар)\s+([^,;]+)",
        address,
        flags=re.IGNORECASE,
    )

    if match:
        street = match.group(0).strip()

        street = re.sub(
            r"\s+(?:дом|д\.)?\s*\d+[а-яa-z]?$",
            "",
            street,
            flags=re.IGNORECASE,
        )

        return street.strip()

    return address.split(",")[-1].strip() or address


def top_roads(reports):
    """
    Рейтинг по активным обращениям.

    Учитываем:
    - максимальную срочность обращения
    - количество обращений
    - поддержку жителей
    """

    groups = {}

    for report in reports:

        if report.get("status") in (
            "Исправлено",
            "Отклонено",
        ):
            continue

        name = road_name(
            report.get("address")
        )

        if name == "Адрес не указан":
            continue

        key = name.casefold()

        if key not in groups:

            groups[key] = {
                "Улица / участок": name,
                "Заявок": 0,
                "Голосов": 0,
                "Макс. срочность": 0,
                "Номера": [],
            }

        item = groups[key]

        item["Заявок"] += 1

        item["Голосов"] += int(
            report.get("votes_count") or 0
        )

        item["Макс. срочность"] = max(
            item["Макс. срочность"],
            float(
                report.get("priority_score") or 0
            ),
        )

        item["Номера"].append(
            str(report.get("id"))
        )

    ranking = []

    for item in groups.values():

        base = item["Макс. срочность"]

        reports_bonus = min(
            15,
            item["Заявок"] * 3,
        )

        votes_bonus = min(
            10,
            item["Голосов"],
        )

        item["Рейтинг"] = round(
            min(
                100,
                base + reports_bonus + votes_bonus,
            ),
            1,
        )

        item["Обращения"] = ", ".join(
            "#" + number
            for number in item.pop("Номера")
        )

        ranking.append(item)

    ranking.sort(
        key=lambda item: (
            item["Рейтинг"],
            item["Заявок"],
        ),
        reverse=True,
    )

    return ranking


def show_report(report):

    rid = int(report["id"])

    with st.container(border=True):

        left, right = st.columns([1, 2])

        with left:

            show_photo(
                report.get("image_path"),
                "Фото проблемы",
            )

        with right:

            st.subheader(
                f"#{rid} · "
                f"{report.get('defect_type', 'Дефект')}"
            )

            st.write(
                "📍",
                report.get("address") or "Адрес не указан",
            )

            st.write(
                "**Статус:**",
                report.get("status", "Новая"),
            )

            st.write(
                "**Срочность:**",
                report.get("priority_score", 0),
                "/ 100",
            )

            st.caption(
                "Создано: "
                + str(report.get("created_at", ""))
            )

            if report.get("mode") == "ai":

                st.caption(
                    "🤖 Тип повреждения предложен моделью "
                    "и подтверждён при отправке"
                )

            votes = int(
                report.get("votes_count") or 0
            )

            if st.button(
                f"👍 Поддержать ({votes})",
                key=f"vote_{rid}",
            ):

                ok, msg = add_vote(
                    rid,
                    st.session_state.voter_token,
                )

                if ok:
                    st.rerun()

                else:
                    st.info(msg)

        # Фото после ремонта

        if report.get("after_image_path"):

            with st.expander("Фото после ремонта"):

                show_photo(
                    report["after_image_path"],
                    "После ремонта",
                )

        # Комментарии

        with st.expander(
            f"💬 Комментарии "
            f"({report.get('comments_count', 0)})"
        ):

            for comment in list_comments(rid):

                st.write(
                    f"**{comment['author']}**: "
                    f"{comment['body']}"
                )

                st.caption(
                    str(comment["created_at"])
                )

            with st.form(
                f"comments_{rid}",
                clear_on_submit=True,
            ):

                author = st.text_input(
                    "Имя",
                    value="Житель Тараза",
                )

                message = st.text_area(
                    "Комментарий",
                    max_chars=500,
                )

                if st.form_submit_button("Отправить"):

                    ok, msg = add_comment(
                        rid,
                        message,
                        author,
                    )

                    if ok:
                        st.rerun()

                    else:
                        st.warning(msg)

        # История

        with st.expander("История статусов"):
            show_history(rid)


# ============================================================
# БОКОВАЯ ПАНЕЛЬ
# ============================================================

with st.sidebar:

    st.markdown("""
<div class="taraz-hero">
    <h1>🛣️ Taraz Road AI</h1>
    <p>
        Умная система мониторинга дорог Тараза.
        Сообщайте о повреждениях, отслеживайте ремонт
        и помогайте сделать город безопаснее.
    </p>
</div>
""", unsafe_allow_html=True)

    st.caption("Digital Taraz · Прототип")


# ============================================================
# ГЛАВНАЯ
# ============================================================

st.title("🛣️ Taraz Road AI")

st.write(
    "Фото → анализ ИИ → местоположение "
    "→ обращение → контроль ремонта"
)

reports = list_reports()

active = sum(
    r.get("status") != "Исправлено"
    for r in reports
)

fixed = sum(
    r.get("status") == "Исправлено"
    for r in reports
)

c1, c2, c3, c4 = st.columns(4)

c1.metric("Всего обращений", len(reports))

c2.metric("Активные", active)

c3.metric("Исправлено", fixed)

c4.metric(
    "Голосов жителей",
    sum(
        int(r.get("votes_count") or 0)
        for r in reports
    ),
)


# ============================================================
# ВКЛАДКИ
# ============================================================

# Отдельной вкладки AI больше нет!

tab_new, tab_feed, tab_map, tab_status, tab_admin = st.tabs(
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

    st.subheader("1. Сделайте фото проблемы")

    source_type = st.radio(
        "Способ добавления фото",
        [
            "📷 Камера телефона",
            "🖼️ Галерея / файл",
        ],
        horizontal=True,
    )

    photo_key = (
        f"photo_{st.session_state.upload_key}"
    )

    # Камера телефона

    if source_type.startswith("📷"):

        source = st.camera_input(
            "Сфотографировать повреждение",
            key=photo_key + "_camera",
        )

    # Галерея телефона / файл компьютера

    else:

        source = st.file_uploader(
            "Выбрать фотографию",
            type=[
                "jpg",
                "jpeg",
                "png",
                "webp",
            ],
            key=photo_key + "_gallery",
        )

    data = None
    analysis = None

    # Автоматический ИИ-анализ

    if source is not None:

        try:

            data = photo_bytes(source)

            st.image(
                data,
                caption="Фото обращения",
                width=450,
            )

            analysis = ai_for_photo(data)

            show_ai(
                analysis,
                show_photo=True,
            )

        except Exception as exc:

            st.error(
                f"Не удалось обработать фото: {exc}"
            )

    # --------------------------------------------------------
    # ТИП ПРОБЛЕМЫ
    # --------------------------------------------------------

    st.subheader("2. Проверьте описание проблемы")

    if "issue_type" not in st.session_state:
        st.session_state.issue_type = "Другая проблема"

    if "issue_severity" not in st.session_state:
        st.session_state.issue_severity = 5

    defect_type = st.selectbox(
        "Тип проблемы",
        ISSUES,
        key="issue_type",
    )

    severity = st.slider(
        "Серьёзность (можно исправить оценку ИИ)",
        1,
        10,
        key="issue_severity",
    )

    # --------------------------------------------------------
    # ГЕОЛОКАЦИЯ
    # --------------------------------------------------------

    st.subheader("3. Укажите местоположение")

    location_mode = st.radio(
        "Как указать место?",
        [
            "📍 GPS телефона",
            "🗺️ Выбрать на карте",
            "✍️ Координаты",
            "🏠 Только адрес",
        ],
        horizontal=True,
    )

    lat = 0.0
    lon = 0.0

    # GPS

    if location_mode.startswith("📍"):

        st.caption(
            "Разрешите браузеру доступ к местоположению. "
            "Работает на HTTPS или localhost."
        )

        gps = streamlit_geolocation()

        if (
            isinstance(gps, dict)
            and gps.get("latitude") is not None
            and gps.get("longitude") is not None
        ):

            st.session_state.last_lat = float(
                gps["latitude"]
            )

            st.session_state.last_lon = float(
                gps["longitude"]
            )

        if (
            "last_lat" in st.session_state
            and "last_lon" in st.session_state
        ):

            lat = st.session_state.last_lat
            lon = st.session_state.last_lon

            st.success(
                f"GPS: {lat:.6f}, {lon:.6f}"
            )

        else:

            st.warning(
                "GPS не получен. Выбери точку "
                "на карте либо введи адрес."
            )

    # ВЫБОР ТОЧКИ НА КАРТЕ

    elif location_mode.startswith("🗺️"):

        center = [
            st.session_state.get(
                "last_lat",
                42.9000,
            ),
            st.session_state.get(
                "last_lon",
                71.3667,
            ),
        ]

        map_choose = folium.Map(
            location=center,
            zoom_start=13,
        )

        result_map = st_folium(
            map_choose,
            height=340,
            use_container_width=True,
            returned_objects=["last_clicked"],
            key="choose_location",
        )

        point = (
            result_map or {}
        ).get("last_clicked")

        if point:

            st.session_state.last_lat = float(
                point["lat"]
            )

            st.session_state.last_lon = float(
                point["lng"]
            )

        if (
            "last_lat" in st.session_state
            and "last_lon" in st.session_state
        ):

            lat = st.session_state.last_lat
            lon = st.session_state.last_lon

            st.success(
                f"Выбрано: {lat:.6f}, {lon:.6f}"
            )

        else:

            st.info(
                "Нажми на нужное место на карте."
            )

    # РУЧНЫЕ КООРДИНАТЫ

    elif location_mode.startswith("✍️"):

        a, b = st.columns(2)

        txt_lat = a.text_input(
            "Широта",
            placeholder="42.900000",
        )

        txt_lon = b.text_input(
            "Долгота",
            placeholder="71.366700",
        )

        if txt_lat.strip() and txt_lon.strip():

            try:

                lat = float(
                    txt_lat.replace(",", ".")
                )

                lon = float(
                    txt_lon.replace(",", ".")
                )

            except ValueError:

                st.warning(
                    "Координаты должны быть числами"
                )

    # АДРЕС

    address = st.text_input(
        "Адрес или ориентир",
        placeholder="Тараз, улица, дом или ориентир",
    )

    if lat == 0 and lon == 0:

        st.caption(
            "Точка на карте не будет создана "
            "без реальных координат."
        )

    agreed = st.checkbox(
        "Подтверждаю достоверность обращения"
    )

    # --------------------------------------------------------
    # СОХРАНЕНИЕ
    # --------------------------------------------------------

    if st.button(
        "🚀 Отправить обращение",
        type="primary",
        width="stretch",
    ):

        if data is None:

            st.error("Добавь фотографию")

        elif not address.strip():

            st.error("Укажи адрес")

        elif not agreed:

            st.error(
                "Подтверди достоверность информации"
            )

        elif not (
            -90 <= lat <= 90
            and -180 <= lon <= 180
        ):

            st.error("Недопустимые координаты")

        else:

            if (
                analysis
                and analysis.get("mode") == "ai"
            ):

                suggestion = detected_type(
                    analysis.get("label")
                )

            else:
                suggestion = None

            ai_used = bool(
                suggestion
                and suggestion == defect_type
                and int(
                    analysis.get("detections_count") or 0
                ) > 0
            )

            if ai_used:

                confidence = float(
                    analysis.get("confidence") or 0
                )

            else:
                confidence = 0.0

            priority = min(
                100,
                round(
                    severity * 8
                    + confidence * 20
                ),
            )

            try:

                rid, duplicate = add_report(
                    image_bytes=data,
                    defect_type=defect_type,
                    confidence=confidence,
                    latitude=lat,
                    longitude=lon,
                    address=address.strip(),
                    severity=severity,
                    priority_score=priority,
                    mode="ai" if ai_used else "manual",
                )

                if duplicate:

                    st.info(
                        f"Похожая заявка уже создана: #{rid}"
                    )

                else:

                    st.success(
                        f"Обращение #{rid} сохранено!"
                    )

                    st.session_state.upload_key += 1

                    st.session_state.pop(
                        "ai_photo_hash",
                        None,
                    )

                    st.session_state.pop(
                        "ai_result",
                        None,
                    )

            except Exception as exc:

                st.error(
                    f"Ошибка сохранения: {exc}"
                )


# ============================================================
# 2. ЛЕНТА ПРОБЛЕМ
# ============================================================

with tab_feed:

    st.subheader("Обращения жителей")

    a, b, c = st.columns([1, 1, 2])

    status_filter = a.selectbox(
        "Статус",
        ["Все"] + STATUSES,
    )

    sort = b.selectbox(
        "Сортировка",
        [
            "Срочные",
            "Новые",
            "Популярные",
        ],
    )

    query = c.text_input(
        "Поиск по номеру, адресу или типу"
    )

    sort_key = {
        "Срочные": "priority",
        "Новые": "newest",
        "Популярные": "popular",
    }[sort]

    rows = list_reports(
        sort_by=sort_key
    )

    for report in rows:

        if (
            status_filter != "Все"
            and report.get("status") != status_filter
        ):
            continue

        searchable = (
            str(report.get("id", ""))
            + " "
            + str(report.get("address", ""))
            + " "
            + str(report.get("defect_type", ""))
        ).lower()

        if query and query.lower() not in searchable:
            continue

        show_report(report)


# ============================================================
# 3. КАРТА
# ============================================================

with tab_map:

    st.subheader("Карта дорожных проблем")

    status_for_map = st.selectbox(
        "Статус на карте",
        ["Все"] + STATUSES,
    )

    road_map = folium.Map(
        location=[42.9000, 71.3667],
        zoom_start=12,
    )

    markers = 0

    for report in reports:

        if (
            status_for_map != "Все"
            and report.get("status") != status_for_map
        ):
            continue

        lat = float(
            report.get("latitude") or 0
        )

        lon = float(
            report.get("longitude") or 0
        )

        if not (
            -90 <= lat <= 90
            and -180 <= lon <= 180
        ):
            continue

        if lat == 0 and lon == 0:
            continue

        priority = float(
            report.get("priority_score") or 0
        )

        if priority >= 75:
            color = "red"

        elif priority >= 45:
            color = "orange"

        else:
            color = "green"

        folium.Marker(
            [lat, lon],
            tooltip=f"Обращение #{report['id']}",
            popup=folium.Popup(
                f"#{report['id']} · "
                f"{report.get('defect_type')} · "
                f"{report.get('status')}",
                max_width=260,
            ),
            icon=folium.Icon(
                color=color
            ),
        ).add_to(road_map)

        markers += 1

    st_folium(
        road_map,
        height=520,
        use_container_width=True,
        key="main_map",
    )

    st.caption(
        f"Точек на карте: {markers}. "
        "Красный — срочно, "
        "оранжевый — средне, "
        "зелёный — ниже."
    )


# ============================================================
# 4. ПРОВЕРКА СТАТУСА
# ============================================================

with tab_status:

    st.subheader(
        "Проверить статус обращения"
    )

    rid = st.number_input(
        "Номер обращения",
        min_value=1,
        step=1,
        value=1,
    )

    if st.button("🔎 Найти"):

        report = get_report(rid)

        if report:
            show_report(report)

        else:
            st.warning(
                "Обращение не найдено"
            )


# ============================================================
# 5. ПАНЕЛЬ АДМИНИСТРАТОРА
# ============================================================


# ============================================================
# НОВАЯ ПАНЕЛЬ АДМИНИСТРАТОРА
# ============================================================

with tab_admin:

    st.subheader(
        "Панель управления городскими обращениями"
    )

    secret = os.environ.get(
        "ADMIN_PASSWORD",
        "",
    )

    try:
        secret = str(
            st.secrets.get(
                "ADMIN_PASSWORD",
                secret,
            )
        )
    except Exception:
        pass

    if not secret:

        st.error(
            "Для доступа добавь ADMIN_PASSWORD "
            "в Streamlit Secrets."
        )

        st.stop()

    password = st.text_input(
        "Пароль администратора",
        type="password",
        key="admin_password",
    )

    if not hmac.compare_digest(password, secret):

        st.info(
            "Введите пароль администратора."
        )

        st.stop()

    # --------------------------------------------------------
    # ОБЩАЯ СТАТИСТИКА
    # --------------------------------------------------------

    active_reports = [
        r for r in reports
        if r.get("status") not in (
            "Исправлено",
            "Отклонено",
        )
    ]

    critical_reports = [
        r for r in active_reports
        if float(
            r.get("priority_score") or 0
        ) >= 75
    ]

    roads = top_roads(reports)

    m1, m2, m3, m4 = st.columns(4)

    m1.metric(
        "Всего обращений",
        len(reports),
    )

    m2.metric(
        "Ожидают решения",
        len(active_reports),
    )

    m3.metric(
        "Срочные обращения",
        len(critical_reports),
    )

    m4.metric(
        "Проблемных участков",
        len(roads),
    )

    st.divider()

    dashboard, ranking_tab, manage, export = st.tabs(
        [
            "📊 Аналитика",
            "🚧 Топ дорог",
            "🛠️ Управление",
            "📥 Экспорт",
        ]
    )

    # ========================================================
    # АНАЛИТИКА
    # ========================================================

    with dashboard:

        st.markdown(
            "### Статистика дорожных обращений"
        )

        if reports:

            df = pd.DataFrame(reports)

            st.markdown("#### Обращения по статусам")

            counts = (
                df["status"]
                .fillna("Не указан")
                .value_counts()
            )

            st.bar_chart(counts)

            st.markdown(
                "#### Самые срочные обращения"
            )

            urgent = sorted(
                active_reports,
                key=lambda r: float(
                    r.get("priority_score") or 0
                ),
                reverse=True,
            )[:10]

            if urgent:

                table = pd.DataFrame([
                    {
                        "№": r.get("id"),
                        "Адрес": r.get("address"),
                        "Проблема": r.get("defect_type"),
                        "Приоритет": r.get(
                            "priority_score"
                        ),
                        "Статус": r.get("status"),
                    }
                    for r in urgent
                ])

                st.dataframe(
                    table,
                    hide_index=True,
                    width="stretch",
                )

            else:

                st.success(
                    "Открытых срочных обращений нет."
                )

        else:

            st.info(
                "Пока недостаточно данных."
            )

    # ========================================================
    # ТОП ДОРОГ
    # ========================================================

    with ranking_tab:

        st.markdown(
            "### 🚧 Топ-10 проблемных дорог"
        )

        st.caption(
            "Рейтинг основан на количестве "
            "открытых обращений, срочности "
            "и голосах жителей."
        )

        if roads:

            top = roads[:10]

            ranking_df = pd.DataFrame(top)

            st.dataframe(
                ranking_df[
                    [
                        "Улица / участок",
                        "Рейтинг",
                        "Заявок",
                        "Голосов",
                        "Макс. срочность",
                        "Обращения",
                    ]
                ],
                hide_index=True,
                width="stretch",
            )

            st.markdown(
                "#### Визуальное сравнение"
            )

            chart_data = (
                ranking_df
                .set_index("Улица / участок")["Рейтинг"]
            )

            st.bar_chart(
                chart_data,
                horizontal=True,
            )

        else:

            st.info(
                "Нет активных обращений "
                "с указанным адресом."
            )

        st.caption(
            "Это предварительный рейтинг. "
            "Для более точной группировки "
            "нужны нормализованные адреса "
            "и географические данные."
        )

    # ========================================================
    # УПРАВЛЕНИЕ
    # ========================================================

    with manage:

        st.markdown(
            "### 🛠️ Управление обращениями"
        )

        search = st.text_input(
            "Поиск по номеру или адресу",
            key="admin_search_v2",
        )

        status_filter = st.selectbox(
            "Фильтр по статусу",
            ["Все"] + STATUSES,
            key="admin_filter_v2",
        )

        ordered_reports = sorted(
            reports,
            key=lambda r: float(
                r.get("priority_score") or 0
            ),
            reverse=True,
        )

        for report in ordered_reports:

            rid = int(report["id"])

            if (
                status_filter != "Все"
                and report.get("status") != status_filter
            ):
                continue

            searchable = (
                str(rid)
                + " "
                + str(report.get("address") or "")
            ).casefold()

            if (
                search
                and search.casefold() not in searchable
            ):
                continue

            with st.expander(
                f"#{rid} · "
                f"{report.get('defect_type')} · "
                f"{report.get('status')} · "
                f"{report.get('priority_score', 0)}/100"
            ):

                left, right = st.columns([1, 2])

                with left:

                    show_photo(
                        report.get("image_path"),
                        "До ремонта",
                    )

                    if report.get("after_image_path"):

                        show_photo(
                            report.get("after_image_path"),
                            "После ремонта",
                        )

                with right:

                    st.write(
                        "**Адрес:**",
                        report.get("address")
                        or "Не указан",
                    )

                    st.write(
                        "**Поддержали:**",
                        report.get("votes_count") or 0,
                    )

                    if report.get("mode") == "ai":

                        st.success(
                            "🤖 Обращение с AI-анализом"
                        )

                    else:

                        st.caption(
                            "Ручное определение дефекта"
                        )

                    # Повторная проверка ИИ

                    if st.button(
                        "🤖 Проверить фото через ИИ",
                        key=f"admin_ai_v2_{rid}",
                    ):

                        image_path = report.get(
                            "image_path"
                        )

                        if (
                            image_path
                            and Path(str(image_path)).is_file()
                        ):

                            result = detect_road_damage(
                                Path(image_path).read_bytes()
                            )

                            show_ai(
                                result,
                                show_photo=True,
                            )

                        else:

                            st.warning(
                                "Фотография недоступна."
                            )

                    # Изменение статуса

                    current = report.get("status")

                    idx = (
                        STATUSES.index(current)
                        if current in STATUSES
                        else 0
                    )

                    new_status = st.selectbox(
                        "Статус обращения",
                        STATUSES,
                        index=idx,
                        key=f"edit_status_v2_{rid}",
                    )

                    if st.button(
                        "💾 Сохранить статус",
                        key=f"admin_save_v2_{rid}",
                    ):

                        update_status(
                            rid,
                            new_status,
                        )

                        st.rerun()

                st.divider()

                # Фото после ремонта

                st.markdown(
                    "#### 📷 Подтверждение ремонта"
                )

                photo_source = st.radio(
                    "Добавить фото после ремонта",
                    [
                        "🖼️ Галерея",
                        "📷 Камера",
                    ],
                    horizontal=True,
                    key=f"after_source_v2_{rid}",
                )

                if photo_source.startswith("📷"):

                    after = st.camera_input(
                        "Снять отремонтированный участок",
                        key=f"after_cam_v2_{rid}",
                    )

                else:

                    after = st.file_uploader(
                        "Загрузить фотографию",
                        type=[
                            "jpg",
                            "jpeg",
                            "png",
                        ],
                        key=f"after_gallery_v2_{rid}",
                    )

                if after is not None:

                    if st.button(
                        "Сохранить фото после ремонта",
                        key=f"save_after_v2_{rid}",
                    ):

                        save_after_photo(
                            rid,
                            photo_bytes(after),
                        )

                        st.rerun()

                # История

                with st.expander(
                    "История изменения статуса"
                ):

                    show_history(rid)

                # Удаление

                st.divider()

                confirmed = st.checkbox(
                    f"Подтверждаю удаление #{rid}",
                    key=f"confirm_delete_v2_{rid}",
                )

                if st.button(
                    "🗑️ Удалить обращение",
                    key=f"delete_v2_{rid}",
                    disabled=not confirmed,
                ):

                    delete_report(rid)

                    st.rerun()

    # ========================================================
    # ЭКСПОРТ
    # ========================================================

    with export:

        st.markdown(
            "### 📥 Скачать данные обращений"
        )

        if reports:

            columns = [
                "id",
                "defect_type",
                "address",
                "priority_score",
                "status",
                "votes_count",
                "created_at",
            ]

            rows = [
                {
                    key: report.get(key)
                    for key in columns
                }
                for report in reports
            ]

            export_df = pd.DataFrame(rows)

            csv_data = export_df.to_csv(
                index=False
            ).encode("utf-8-sig")

            st.download_button(
                "⬇️ Скачать CSV",
                data=csv_data,
                file_name="taraz_road_reports.csv",
                mime="text/csv",
            )

        else:

            st.info(
                "Нет обращений для экспорта."
            )



# ============================================================
# ПОДВАЛ
# ============================================================

st.divider()

st.caption(
    "Taraz Road AI · Прототип. "
    "AI-оценки требуют проверки специалистом."
)
