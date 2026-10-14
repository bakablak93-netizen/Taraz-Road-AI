
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "reports.db"
UPLOAD_DIR = ROOT / "uploads"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT NOT NULL,
                defect_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                address TEXT,
                severity INTEGER NOT NULL,
                priority_score INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Новая',
                mode TEXT NOT NULL DEFAULT 'demo',
                created_at TEXT NOT NULL,
                request_hash TEXT
            )
        """)

        # Добавляем колонку и в уже существующую базу.
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(reports)"
            ).fetchall()
        }

        if "request_hash" not in columns:
            conn.execute(
                "ALTER TABLE reports ADD COLUMN request_hash TEXT"
            )


def add_report(
    image_bytes,
    defect_type,
    confidence,
    latitude,
    longitude,
    address,
    severity,
    priority_score,
    mode,
):
    address = (address or "").strip()

    # Учитываем фотографию и поля заявки, чтобы не блокировать
    # другие заявки с той же фотографией, но другим адресом.
    fingerprint_data = "|".join([
        hashlib.sha256(image_bytes).hexdigest(),
        str(defect_type),
        f"{float(latitude):.6f}",
        f"{float(longitude):.6f}",
        address.casefold(),
        str(int(severity)),
    ])
    request_hash = hashlib.sha256(
        fingerprint_data.encode("utf-8")
    ).hexdigest()

    now = datetime.now()
    created_at = now.strftime("%Y-%m-%d %H:%M:%S")
    cutoff = (now - timedelta(minutes=10)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    with connect() as conn:
        # Проверяем дубликат в пределах последних 10 минут.
        existing = conn.execute(
            """
            SELECT id FROM reports
            WHERE request_hash = ?
              AND created_at >= ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (request_hash, cutoff),
        ).fetchone()

        if existing:
            return existing["id"], True

        cursor = conn.execute(
            """
            INSERT INTO reports (
                image_path, defect_type, confidence,
                latitude, longitude, address, severity,
                priority_score, status, mode, created_at,
                request_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "", defect_type, float(confidence),
                float(latitude), float(longitude), address,
                int(severity), int(priority_score), "Новая",
                mode, created_at, request_hash,
            ),
        )

        report_id = cursor.lastrowid
        image_path = UPLOAD_DIR / f"report_{report_id}.jpg"

        try:
            image_path.write_bytes(image_bytes)
            conn.execute(
                "UPDATE reports SET image_path = ? WHERE id = ?",
                (str(image_path), report_id),
            )
        except Exception:
            # Не оставляем заявку без сохранённого фото.
            conn.execute(
                "DELETE FROM reports WHERE id = ?",
                (report_id,),
            )
            raise

    return report_id, False


def list_reports():
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reports ORDER BY priority_score DESC, id DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def update_status(report_id, status):
    with connect() as conn:
        conn.execute(
            "UPDATE reports SET status = ? WHERE id = ?",
            (status, int(report_id)),
        )
