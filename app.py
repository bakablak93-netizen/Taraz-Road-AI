import os
import streamlit as st
from services.database import init_db, add_report, list_reports, update_status
from services.detection import detect_road_damage, model_available
from services.priority import calculate_priority, priority_label
from services.geolocation import build_map

st.set_page_config(page_title="Taraz Road AI", page_icon="🛣️", layout="wide")
init_db()

st.title("🛣️ Taraz Road AI")
st.caption("AI-прототип для обнаружения дорожных дефектов и приоритизации ремонта в Таразе")

if model_available():
    st.success("Модель дорожных дефектов найдена. Доступен режим AI-распознавания.")
else:
    st.warning(
        "Сейчас включён демонстрационный режим: настоящие предсказания ИИ недоступны, "
        "пока вы не добавите обученные веса модели в models/road_damage.pt. "
        "Заявки, карта и панель управления уже работают."
    )

tab_report, tab_map, tab_admin = st.tabs(["📷 Новая заявка", "🗺️ Карта дефектов", "🧰 Панель администрации"])

with tab_report:
    st.subheader("Сообщить о дефекте")
    uploaded = st.file_uploader("Загрузите фото дорожного дефекта", type=["jpg", "jpeg", "png"])
    if uploaded:
        st.image(uploaded, caption="Загруженная фотография", use_container_width=True)
        with st.spinner("Анализируем изображение..."):
            result = detect_road_damage(uploaded.getvalue())
        if result["mode"] == "ai":
            st.success("Анализ ИИ завершён.")
            st.write(f"**Результат:** {result['label']}")
            st.write(f"**Уверенность модели:** {result['confidence']:.0%}")
            if result.get("annotated_image") is not None:
                st.image(result["annotated_image"], caption="Результат модели", use_container_width=True)
        else:
            st.info("Демо-режим: изображение показано, но модель не анализировала его. Вы можете зарегистрировать тестовую заявку вручную.")
            st.write("**Тип дефекта для тестовой заявки:** выберите ниже. Это не результат распознавания ИИ.")

        with st.form("new_report"):
            defect_type = st.selectbox("Тип дефекта", ["Выбоина / яма", "Трещины", "Повреждённая разметка", "Другое"])
            address = st.text_input("Адрес или ориентир", placeholder="Например: рядом со школой или перекрёстком")
            col1, col2 = st.columns(2)
            with col1:
                lat = st.number_input("Широта (latitude)", value=42.9000, format="%.6f", help="Укажите реальные координаты или оставьте пример для теста.")
            with col2:
                lon = st.number_input("Долгота (longitude)", value=71.3660, format="%.6f", help="Укажите реальные координаты или оставьте пример для теста.")
            severity = st.slider("Серьёзность дефекта (оценка пользователя)", 0, 100, 60)
            location_score = st.slider("Значимость места (оценка)", 0, 100, 50)
            confirmation_score = st.slider("Подтверждения / повторные сообщения", 0, 100, 20)
            submitted = st.form_submit_button("Сохранить заявку", type="primary")
            if submitted:
                confidence = result["confidence"] * 100 if result["mode"] == "ai" else 50
                score = calculate_priority(severity, location_score, confirmation_score, confidence)
                report_id = add_report(
                    image_bytes=uploaded.getvalue(),
                    defect_type=defect_type,
                    confidence=confidence,
                    latitude=lat,
                    longitude=lon,
                    address=address,
                    severity=severity,
                    priority_score=score,
                    mode=result["mode"],
                )
                st.success(f"Заявка #{report_id} сохранена. Приоритет: {priority_label(score)} ({score}/100).")
                st.info("Для тестовых координат замените значения на точку реального дефекта перед публичной демонстрацией.")

with tab_map:
    st.subheader("Карта зарегистрированных дефектов")
    reports = list_reports()
    if not reports:
        st.info("Пока нет заявок. Добавьте первую на вкладке «Новая заявка».")
    else:
        st.caption(f"Заявок в базе: {len(reports)}")
        map_obj = build_map(reports)
        st.components.v1.html(map_obj._repr_html_(), height=570, scrolling=True)
        st.dataframe(
            [{
                "ID": r["id"], "Тип": r["defect_type"], "Адрес": r["address"] or "Не указан",
                "Приоритет": r["priority_score"], "Уровень": priority_label(r["priority_score"]),
                "Статус": r["status"], "Режим": r["mode"]
            } for r in reports],
            use_container_width=True,
            hide_index=True,
        )

with tab_admin:
    st.subheader("Управление заявками")
    reports = list_reports()
    if not reports:
        st.info("Заявок пока нет.")
    else:
        for r in reports:
            with st.expander(f"Заявка #{r['id']} · {r['defect_type']} · приоритет {r['priority_score']}/100"):
                c1, c2 = st.columns([1, 2])
                with c1:
                    if r["image_path"] and os.path.exists(r["image_path"]):
                        st.image(r["image_path"], use_container_width=True)
                with c2:
                    st.write(f"**Адрес:** {r['address'] or 'Не указан'}")
                    st.write(f"**Координаты:** {r['latitude']:.6f}, {r['longitude']:.6f}")
                    st.write(f"**Уровень:** {priority_label(r['priority_score'])}")
                    st.write(f"**Режим:** {r['mode']}")
                    st.write(f"**Создана:** {r['created_at']}")
                    statuses = ["Новая", "На проверке", "В работе", "Исправлено"]
                    current = r["status"] if r["status"] in statuses else "Новая"
                    new_status = st.selectbox("Статус", statuses, index=statuses.index(current), key=f"status_{r['id']}")
                    if st.button("Сохранить статус", key=f"save_{r['id']}"):
                        update_status(r["id"], new_status)
                        st.success("Статус обновлён.")
                        st.rerun()
