
from pathlib import Path
from io import BytesIO

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "road_damage.pt"

MODEL_REPO = "dronefreak/rdd2022-yolov8s"
MODEL_FILENAME = "best.pt"

_model = None
_model_error = None


CLASS_NAMES = {
    "pothole": "Яма на дороге",
    "longitudinal_crack": "Продольная трещина",
    "transverse_crack": "Поперечная трещина",
    "alligator_crack": "Сетчатые трещины",
}


def model_available():
    """
    True, если модель уже загружена в память
    или существует локальный файл весов.
    """
    return _model is not None or MODEL_PATH.exists()


def _load_model():
    """
    Загружает YOLO.
    Если локального файла нет, скачивает веса
    обученной дорожной модели с Hugging Face.
    """
    global _model, _model_error

    if _model is not None:
        return _model

    try:
        from ultralytics import YOLO

        if MODEL_PATH.exists():
            weights_path = str(MODEL_PATH)
        else:
            from huggingface_hub import hf_hub_download

            weights_path = hf_hub_download(
                repo_id=MODEL_REPO,
                filename=MODEL_FILENAME,
            )

        _model = YOLO(weights_path)
        _model_error = None

        return _model

    except Exception as exc:
        _model_error = str(exc)
        return None



def detect_road_damage(image_bytes):
    """
    Распознаёт повреждения на фотографии
    и оценивает их визуальный масштаб.

    Возвращает:
    - тип дефекта
    - уверенность модели
    - фото с выделенными дефектами
    - количество дефектов
    - примерный охват фотографии
    - оценку серьёзности от 1 до 10
    """

    model = _load_model()

    if model is None:
        return {
            "mode": "demo",
            "label": "Модель недоступна",
            "confidence": 0.0,
            "annotated_image": None,
            "error": _model_error,
        }

    try:
        image = Image.open(
            BytesIO(image_bytes)
        ).convert("RGB")

        width, height = image.size
        image_area = width * height

        results = model.predict(
            source=np.array(image),
            conf=0.25,
            imgsz=640,
            device="cpu",
            verbose=False,
        )

        result = results[0]

        annotated_image = result.plot()[:, :, ::-1]

        # Если модель не обнаружила повреждений
        if result.boxes is None or len(result.boxes) == 0:
            return {
                "mode": "ai",
                "label": "Дефекты не обнаружены",
                "confidence": 0.0,
                "annotated_image": annotated_image,
                "detections_count": 0,
                "coverage_percent": 0.0,
                "severity_score": 0,
                "severity_label": "Не определена",
                "error": None,
            }

        boxes = result.boxes

        # Количество найденных повреждений
        detections_count = len(boxes)

        # Уверенность по каждому обнаружению
        confidences = boxes.conf.cpu().numpy()

        best_index = int(np.argmax(confidences))
        confidence = float(confidences[best_index])

        # Тип самого уверенного обнаружения
        class_id = int(boxes.cls[best_index].item())
        english_name = result.names[class_id]

        russian_name = CLASS_NAMES.get(
            english_name,
            english_name,
        )

        # Координаты прямоугольников вокруг повреждений
        coordinates = boxes.xyxy.cpu().numpy()

        total_box_area = 0.0

        for x1, y1, x2, y2 in coordinates:
            x1 = max(0, min(width, float(x1)))
            x2 = max(0, min(width, float(x2)))
            y1 = max(0, min(height, float(y1)))
            y2 = max(0, min(height, float(y2)))

            box_width = max(0, x2 - x1)
            box_height = max(0, y2 - y1)

            total_box_area += box_width * box_height

        # Доля фотографии, занятая прямоугольниками.
        # При пересечениях возможен двойной подсчёт.
        coverage_percent = min(
            100.0,
            (total_box_area / image_area) * 100
        )

        coverage_percent = round(
            coverage_percent, 1
        )

        # Эвристическая оценка визуального масштаба
        raw_score = (
            1
            + coverage_percent * 0.2
            + min(detections_count, 5) * 0.5
        )

        severity_score = max(
            1,
            min(10, round(raw_score))
        )

        if severity_score >= 8:
            severity_label = "Высокая"
        elif severity_score >= 5:
            severity_label = "Средняя"
        else:
            severity_label = "Низкая"

        return {
            "mode": "ai",
            "label": russian_name,
            "confidence": confidence,
            "annotated_image": annotated_image,
            "detections_count": detections_count,
            "coverage_percent": coverage_percent,
            "severity_score": severity_score,
            "severity_label": severity_label,
            "error": None,
        }

    except Exception as exc:
        return {
            "mode": "demo",
            "label": "Ошибка анализа фотографии",
            "confidence": 0.0,
            "annotated_image": None,
            "error": str(exc),
        }
