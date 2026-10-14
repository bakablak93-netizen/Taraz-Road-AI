from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / 'models' / 'road_damage.pt'
MODEL_REPO = 'dronefreak/rdd2022-yolov8s'
MODEL_FILENAME = 'best.pt'

_model = None
_model_error = None

CLASS_NAMES = {
    'pothole': 'Яма на дороге',
    'longitudinal_crack': 'Трещины на дороге',
    'transverse_crack': 'Трещины на дороге',
    'alligator_crack': 'Трещины на дороге',
    'D00': 'Трещины на дороге',
    'D10': 'Трещины на дороге',
    'D20': 'Трещины на дороге',
    'D40': 'Яма на дороге',
}


def model_available():
    return _model is not None or MODEL_PATH.is_file()


def _load_model():
    global _model, _model_error
    if _model is not None:
        return _model
    try:
        from ultralytics import YOLO
        if MODEL_PATH.is_file():
            path = str(MODEL_PATH)
        else:
            from huggingface_hub import hf_hub_download
            path = hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILENAME)
        _model = YOLO(path)
        _model_error = None
        return _model
    except Exception as exc:
        _model_error = str(exc)
        return None


def _error_result(message):
    return {
        'mode': 'demo', 'label': 'ИИ недоступен',
        'confidence': 0.0, 'annotated_image': None,
        'detections_count': 0, 'coverage_percent': 0.0,
        'severity_score': None, 'error': message,
    }


def detect_road_damage(image_bytes):
    """Реальная YOLO-детекция. Оценка масштаба — эвристика, а не измерение."""
    model = _load_model()
    if model is None:
        return _error_result(_model_error or 'Не удалось скачать или открыть модель.')
    try:
        image = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes))).convert('RGB')
        width, height = image.size
        result = model.predict(
            source=np.asarray(image), conf=0.25, imgsz=640,
            device='cpu', verbose=False,
        )[0]
        annotated = result.plot()[:, :, ::-1].copy()
        if result.boxes is None or len(result.boxes) == 0:
            return {
                'mode': 'ai', 'label': 'Дефекты не обнаружены',
                'confidence': 0.0, 'annotated_image': annotated,
                'detections_count': 0, 'coverage_percent': 0.0,
                'severity_score': None, 'error': None,
            }

        boxes = result.boxes
        confidences = boxes.conf.cpu().numpy()
        idx = int(np.argmax(confidences))
        cls = int(boxes.cls[idx].item())
        raw = str(result.names[cls])
        label = CLASS_NAMES.get(raw, raw)

        # Площадь ограничивающих прямоугольников в пикселях.
        # При пересечении прямоугольники могут считаться дважды.
        box_area = 0.0
        for x1, y1, x2, y2 in boxes.xyxy.cpu().numpy():
            x1, x2 = sorted((max(0.0, min(float(x1), width)), max(0.0, min(float(x2), width))))
            y1, y2 = sorted((max(0.0, min(float(y1), height)), max(0.0, min(float(y2), height))))
            box_area += (x2 - x1) * (y2 - y1)
        coverage = round(min(100.0, 100.0 * box_area / (width * height)), 1)
        count = len(boxes)
        severity = max(1, min(10, round(1 + coverage * 0.2 + min(count, 5) * 0.5)))
        return {
            'mode': 'ai', 'label': label,
            'confidence': float(confidences[idx]),
            'annotated_image': annotated,
            'detections_count': count, 'coverage_percent': coverage,
            'severity_score': severity, 'error': None,
        }
    except Exception as exc:
        return _error_result(str(exc))
