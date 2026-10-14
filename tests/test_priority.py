from services.priority import calculate_priority, priority_label


def test_priority_range():
    assert calculate_priority(100, 100, 100, 100) == 100
    assert calculate_priority(0, 0, 0, 0) == 0


def test_priority_labels():
    assert priority_label(80) == "Высокий"
    assert priority_label(55) == "Средний"
    assert priority_label(20) == "Низкий"
