from pathlib import Path
from io import BytesIO
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "road_damage.pt"
_model = None
_model_error = None


def model_available():
    return MODEL_PATH.exists()


def _load_model():
    global _model, _model_error
    if _model is not None:
        return _model
    if not MODEL_PATH.exists():
        return None
    try:
        from ultralytics import YOLO
        _model = YOLO(str(MODEL_PATH))
        return _model
    except Exception as exc:
        _model_error = str(exc)
        return None


def detect_road_damage(image_bytes):
    """
    Uses custom road-damage YOLO weights if models/road_damage.pt exists.
    Without weights, returns a clearly labeled demo result; it does NOT claim AI detection.
    """
    model = _load_model()
    if model is None:
        return {
            "mode": "demo",
            "label": "Демо: модель не подключена",
            "confidence": 0.0,
            "annotated_image": None,
            "error": _model_error,
        }

    try:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        results = model.predict(np.array(image), verbose=False)
        result = results[0]
        annotated = result.plot()[:, :, ::-1]
        if result.boxes is None or len(result.boxes) == 0:
            return {
                "mode": "ai", "label": "Дефект не обнаружен моделью",
                "confidence": 0.0, "annotated_image": annotated
            }
        confidences = result.boxes.conf.cpu().numpy()
        best_index = int(np.argmax(confidences))
        confidence = float(confidences[best_index])
        cls_id = int(result.boxes.cls[best_index].item())
        names = result.names
        label = names.get(cls_id, f"Класс {cls_id}") if isinstance(names, dict) else str(cls_id)
        return {
            "mode": "ai", "label": label, "confidence": confidence,
            "annotated_image": annotated
        }
    except Exception as exc:
        return {
            "mode": "demo", "label": "Ошибка анализа; можно сохранить тестовую заявку",
            "confidence": 0.0, "annotated_image": None, "error": str(exc)
        }
