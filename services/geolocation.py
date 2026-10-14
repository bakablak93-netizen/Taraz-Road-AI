import folium


def build_map(reports):
    # Approximate city center used only to frame the map; pins use each report's coordinates.
    m = folium.Map(location=[42.9000, 71.3660], zoom_start=12, control_scale=True)
    colors = {"Высокий": "red", "Средний": "orange", "Низкий": "green"}
    for r in reports:
        score = int(r["priority_score"])
        level = "Высокий" if score >= 75 else ("Средний" if score >= 45 else "Низкий")
        popup = (
            f"<b>Заявка #{r['id']}</b><br>"
            f"Тип: {r['defect_type']}<br>"
            f"Адрес: {r['address'] or 'Не указан'}<br>"
            f"Приоритет: {score}/100 ({level})<br>"
            f"Статус: {r['status']}<br>"
            f"Режим: {r['mode']}"
        )
        folium.Marker(
            location=[r["latitude"], r["longitude"]],
            popup=folium.Popup(popup, max_width=300),
            tooltip=f"#{r['id']} · {level}",
            icon=folium.Icon(color=colors[level], icon="warning-sign")
        ).add_to(m)
    return m
