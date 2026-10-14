
import os
import csv
import io
import streamlit as st

from services.database import init_db, add_report, list_reports, update_status
from services.detection import detect_road_damage, model_available
from services.priority import calculate_priority, priority_label
from services.geolocation import build_map

st.set_page_config(page_title="Taraz Road AI", page_icon="🛣️", layout="wide")
init_db()

st.title("🛣️ Taraz Road AI")
st.caption("Платформа для регистрации дорожных дефектов и планирования ремонта в Таразе")

if model_available():
    st.success("Модель найдена: доступен режим AI-распознавания.")
else:
    st.warning("Демо-режим: обученная модель не подключена. Не выдавайте тестовые результаты за настоящее распознавание ИИ.")

tab_report, tab_map, tab_admin = st.tabs(
    ["📷 Новая заявка", "🗺️ Карта дефектов", "🧰 Панель администрации"]
)

with tab_report:
    st.subheader("📷 Сообщить о дорожном дефекте")
    uploaded = st.file_uploader("Загрузите фотографию дороги", type=["jpg", "jpeg", "png"])

    if uploaded:
        st.image(uploaded, caption="Загруженная фотография", use_container_width=True)

        with st.spinner("Проверяем изображение..."):
            result = detect_road_damage(uploaded.getvalue())

        if result["mode"] == "ai":
            st.success("Анализ модели завершён.")
            st.write(f"**Предполагаемый дефект:** {result['label']}")
            st.write(f"**Уверенность модели:** {result['confidence']:.0%}")
            if result.get("annotated_image") is not None:
                st.image(result["annotated_image"], caption="Результат модели", use_container_width=True)
        else:
            st.info("Демонстрационный режим: автоматическое распознавание пока не выполняется. Тип дефекта укажите вручную.")

        with st.form("new_report"):
            defect_type = st.selectbox(
                "Тип дефекта",
                ["Выбоина / яма", "Трещины", "Повреждённая разметка", "Другое"]
            )
            address = st.text_input("Адрес или ориентир", placeholder="Улица, перекрёсток или ближайшее здание")

            col1, col2 = st.columns(2)
            with col1:
                lat = st.number_input("Широта", value=42.9000, format="%.6f")
            with col2:
                lon = st.number_input("Долгота", value=71.3660, format="%.6f")

            severity = st.slider("Серьёзность дефекта", 0, 100, 60)
            location_score = st.slider("Значимость места", 0, 100, 50)
            confirmation_score = st.slider("Подтверждения / повторные сообщения", 0, 100, 20)

            submitted = st.form_submit_button("Сохранить заявку", type="primary")

            if submitted:
                confidence = result["confidence"] * 100 if result["mode"] == "ai" else 0
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
                st.info("Проверьте координаты: значения по умолчанию подходят только для теста.")

with tab_map:
    st.subheader("🗺️ Карта зарегистрированных дефектов")
    reports = list_reports()

    if not reports:
        st.info("Заявок пока нет. Добавьте первую на вкладке «Новая заявка».")
    else:
        st.caption(f"Всего заявок: {len(reports)}")
        map_obj = build_map(reports)
        st.components.v1.html(map_obj._repr_html_(), height=570, scrolling=True)

        st.dataframe(
            [{
                "ID": r["id"],
                "Тип": r["defect_type"],
                "Адрес": r["address"] or "Не указан",
                "Приоритет": r["priority_score"],
                "Уровень": priority_label(r["priority_score"]),
                "Статус": r["status"],
                "Режим": r["mode"],
            } for r in reports],
            use_container_width=True,
            hide_index=True,
        )

with tab_admin:
    st.subheader("🧰 Панель администрации")
    reports = list_reports()

    if not reports:
        st.info("Заявок пока нет. Создайте заявку на первой вкладке.")
    else:
        total = len(reports)
        fixed = sum(r["status"] == "Исправлено" for r in reports)
        active = total - fixed
        high = sum(int(r["priority_score"]) >= 75 and r["status"] != "Исправлено" for r in reports)

        st.markdown("### 📊 Сводка")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Всего заявок", total)
        c2.metric("Требуют внимания", active)
        c3.metric("Высокий приоритет", high)
        c4.metric("Исправлено", fixed)
        st.progress(fixed / total, text=f"Доля исправленных заявок: {fixed / total:.0%}")

        def priority_group(score):
            score = int(score)
            if score >= 75:
                return "Высокий"
            if score >= 40:
                return "Средний"
            return "Низкий"

        st.markdown("### 🔎 Фильтры")
        f1, f2 = st.columns(2)
        with f1:
            selected_status = st.selectbox(
                "Статус",
                ["Все"] + sorted({r["status"] for r in reports})
            )
        with f2:
            selected_priority = st.selectbox(
                "Приоритет", ["Все", "Высокий", "Средний", "Низкий"]
            )

        filtered = reports
        if selected_status != "Все":
            filtered = [r for r in filtered if r["status"] == selected_status]
        if selected_priority != "Все":
            filtered = [r for r in filtered if priority_group(r["priority_score"]) == selected_priority]

        st.markdown(f"### 📋 Заявки ({len(filtered)})")

        for r in filtered:
            score = int(r["priority_score"])
            group = priority_group(score)

            with st.expander(f"#{r['id']} · {r['defect_type']} · {group} приоритет ({score}/100)"):
                col1, col2 = st.columns([1, 2])
                with col1:
                    if r["image_path"] and os.path.exists(r["image_path"]):
                        st.image(r["image_path"], caption="Фото дефекта", use_container_width=True)
                with col2:
                    st.write(f"**Адрес:** {r['address'] or 'Не указан'}")
                    st.write(f"**Координаты:** {r['latitude']:.6f}, {r['longitude']:.6f}")
                    st.write(f"**Приоритет:** {group} ({score}/100)")
                    st.write(f"**Режим:** {r['mode']}")
                    st.write(f"**Создана:** {r['created_at']}")

                    options = ["Новая", "На проверке", "В работе", "Исправлено"]
                    current = r["status"] if r["status"] in options else "Новая"
                    new_status = st.selectbox(
                        "Статус ремонта", options,
                        index=options.index(current), key=f"status_{r['id']}"
                    )

                    if st.button("Сохранить статус", key=f"save_{r['id']}"):
                        update_status(r["id"], new_status)
                        st.success("Статус обновлён!")
                        st.rerun()

        st.markdown("### 📥 Экспорт отчёта")
        export_rows = [{
            "ID": r["id"],
            "Тип дефекта": r["defect_type"],
            "Адрес": r["address"] or "",
            "Широта": r["latitude"],
            "Долгота": r["longitude"],
            "Приоритет": r["priority_score"],
            "Группа приоритета": priority_group(r["priority_score"]),
            "Статус": r["status"],
            "Режим": r["mode"],
            "Дата": r["created_at"],
        } for r in filtered]

        buffer = io.StringIO()
        fields = list(export_rows[0].keys()) if export_rows else [
            "ID", "Тип дефекта", "Адрес", "Широта", "Долгота",
            "Приоритет", "Группа приоритета", "Статус", "Режим", "Дата"
        ]
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(export_rows)

        st.download_button(
            "⬇️ Скачать отчёт CSV",
            data="\ufeff" + buffer.getvalue(),
            file_name="taraz_road_ai_report.csv",
            mime="text/csv"
        )

        st.caption("Приоритет — ориентировочная оценка прототипа, не официальный норматив.")
