import os
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "reports.db"
UPLOAD_DIR = ROOT / "uploads"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def connect():
    conn = sqlite3.connect(DB_PATH)
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
                created_at TEXT NOT NULL
            )
        """)


def add_report(image_bytes, defect_type, confidence, latitude, longitude,
               address, severity, priority_score, mode):
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO reports (image_path, defect_type, confidence, latitude, longitude, address, severity, priority_score, status, mode, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("", defect_type, float(confidence), float(latitude), float(longitude),
             address.strip(), int(severity), int(priority_score), "Новая", mode,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        report_id = cursor.lastrowid
        image_path = UPLOAD_DIR / f"report_{report_id}.jpg"
        image_path.write_bytes(image_bytes)
        conn.execute("UPDATE reports SET image_path = ? WHERE id = ?", (str(image_path), report_id))
        return report_id


def list_reports():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM reports ORDER BY priority_score DESC, id DESC").fetchall()
        return [dict(row) for row in rows]


def update_status(report_id, status):
    with connect() as conn:
        conn.execute("UPDATE reports SET status = ? WHERE id = ?", (status, int(report_id)))
