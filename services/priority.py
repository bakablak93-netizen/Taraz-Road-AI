def calculate_priority(severity, location_score, confirmation_score, confidence_score):
    """Примерная эвристика для прототипа, не официальный стандарт города."""
    score = (
        0.40 * float(severity)
        + 0.25 * float(location_score)
        + 0.20 * float(confirmation_score)
        + 0.15 * float(confidence_score)
    )
    return max(0, min(100, round(score)))


def priority_label(score):
    score = float(score)
    if score >= 75:
        return "Высокий"
    if score >= 45:
        return "Средний"
    return "Низкий"
