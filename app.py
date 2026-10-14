import os
import streamlit as st
from services.database import init_db, add_report, list_reports, update_status
from services.detection import detect_road_damage, model_available
from services.priority import calculate_priority, priority_label
from services.geolocation import build_map
import csv
import io

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
with tab_admin:
    st.subheader("🧰 Панель администрации")
    reports = list_reports()

    if not reports:
        st.info("Заявок пока нет. Добавьте первую на вкладке «Новая заявка».")
    else:
        # Основные показатели
        total = len(reports)
        fixed = sum(r["status"] == "Исправлено" for r in reports)
        active = total - fixed
        high = sum(
            int(r["priority_score"]) >= 75 and r["status"] != "Исправлено"
            for r in reports
        )

        st.markdown("### 📊 Сводка по дорожным дефектам")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Всего заявок", total)
        c2.metric("Требуют внимания", active)
        c3.metric("Высокий приоритет", high)
        c4.metric("Исправлено", fixed)

        st.progress(fixed / total, text=f"Доля исправленных заявок: {fixed / total:.0%}")

        # Фильтры
        st.markdown("### 🔎 Фильтры")
        f1, f2 = st.columns(2)

        statuses = ["Все"] + sorted({r["status"] for r in reports})
        with f1:
            chosen_status = st.selectbox("Статус", statuses)

        with f2:
            chosen_priority = st.selectbox(
                "Приоритет",
                ["Все", "Высокий", "Средний", "Низкий"]
            )

        def priority_group(score):
            score = int(score)
            if score >= 75:
                return "Высокий"
            elif score >= 40:
                return "Средний"
            return "Низкий"

        filtered = reports

        if chosen_status != "Все":
            filtered = [
                r for r in filtered if r["status"] == chosen_status
            ]

        if chosen_priority != "Все":
            filtered = [
                r for r in filtered
                if priority_group(r["priority_score"]) == chosen_priority
            ]

        # Список заявок
        st.markdown(f"### 📋 Заявки ({len(filtered)})")

        for r in filtered:
            score = int(r["priority_score"])
            group = priority_group(score)

            with st.expander(
                f"#{r['id']} · {r['defect_type']} · "
                f"{group} приоритет ({score}/100)"
            ):
                col1, col2 = st.columns([1, 2])

                with col1:
                    if r["image_path"] and os.path.exists(r["image_path"]):
                        st.image(
                            r["image_path"],
                            caption="Фото дефекта",
                            use_container_width=True
                        )

                with col2:
                    st.write(f"**Адрес:** {r['address'] or 'Не указан'}")
                    st.write(
                        f"**Координаты:** "
                        f"{r['latitude']:.6f}, {r['longitude']:.6f}"
                    )
                    st.write(f"**Приоритет:** {group} ({score}/100)")
                    st.write(f"**Режим:** {r['mode']}")
                    st.write(f"**Создана:** {r['created_at']}")

                    options = [
                        "Новая", "На проверке", "В работе", "Исправлено"
                    ]
                    current = (
                        r["status"] if r["status"] in options else "Новая"
                    )

                    new_status = st.selectbox(
                        "Статус ремонта",
                        options,
                        index=options.index(current),
                        key=f"status_{r['id']}"
                    )

                    if st.button(
                        "Сохранить статус",
                        key=f"save_{r['id']}"
                    ):
                        update_status(r["id"], new_status)
                        st.success("Статус обновлён!")
                        st.rerun()

        # Экспорт в CSV
        st.markdown("### 📥 Экспорт отчёта")

        export_rows = [
            {
                "ID": r["id"],
                "Тип дефекта": r["defect_type"],
                "Адрес": r["address"] or "",
                "Широта": r["latitude"],
                "Долгота": r["longitude"],
                "Приоритет": r["priority_score"],
                "Группа приоритета": priority_group(r["priority_score"]),
                "Статус": r["status"],
                "Режим": r["mode"],
                "Дата": r["created_at"]
            }
            for r in filtered
        ]

        csv_buffer = io.StringIO()
        fieldnames = list(export_rows[0].keys()) if export_rows else [
            "ID", "Тип дефекта", "Адрес", "Широта", "Долгота",
            "Приоритет", "Группа приоритета", "Статус", "Режим", "Дата"
        ]

        writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(export_rows)

        st.download_button(
            "⬇️ Скачать отчёт CSV",
            data="\ufeff" + csv_buffer.getvalue(),
            file_name="taraz_road_ai_report.csv",
            mime="text/csv"
        )

        st.caption(
            "Приоритеты рассчитываются прототипом и не являются "
            "официальной оценкой дорожных служб."
        )
