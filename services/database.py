
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "reports.db"
UPLOAD_DIR = ROOT / "uploads"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

STATUSES = ["Новая", "На проверке", "В работе", "Исправлено"]


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(reports)"
            ).fetchall()
        }

        migrations = {
            "request_hash": "TEXT",
            "votes_count": "INTEGER NOT NULL DEFAULT 0",
            "comments_count": "INTEGER NOT NULL DEFAULT 0",
            "after_image_path": "TEXT",
            "updated_at": "TEXT",
        }

        for name, column_type in migrations.items():
            if name not in columns:
                conn.execute(
                    f"ALTER TABLE reports ADD COLUMN "
                    f"{name} {column_type}"
                )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS report_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                voter_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(report_id, voter_hash),
                FOREIGN KEY(report_id)
                    REFERENCES reports(id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS report_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                author TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(report_id)
                    REFERENCES reports(id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL,
                old_status TEXT,
                new_status TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                FOREIGN KEY(report_id)
                    REFERENCES reports(id) ON DELETE CASCADE
            )
        """)

        # Добавляем начальную запись истории для старых заявок.
        conn.execute("""
            INSERT INTO status_history (
                report_id, old_status, new_status, changed_at
            )
            SELECT r.id, NULL, r.status, r.created_at
            FROM reports r
            WHERE NOT EXISTS (
                SELECT 1 FROM status_history h
                WHERE h.report_id = r.id
            )
        """)


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

    fingerprint = "|".join([
        hashlib.sha256(image_bytes).hexdigest(),
        str(defect_type),
        f"{float(latitude):.6f}",
        f"{float(longitude):.6f}",
        address.casefold(),
        str(int(severity)),
    ])

    request_hash = hashlib.sha256(
        fingerprint.encode("utf-8")
    ).hexdigest()

    now = datetime.now()
    created_at = now.strftime("%Y-%m-%d %H:%M:%S")
    cutoff = (
        now - timedelta(minutes=10)
    ).strftime("%Y-%m-%d %H:%M:%S")

    with connect() as conn:
        existing = conn.execute("""
            SELECT id FROM reports
            WHERE request_hash = ?
              AND created_at >= ?
            ORDER BY id DESC
            LIMIT 1
        """, (request_hash, cutoff)).fetchone()

        if existing:
            return existing["id"], True

        cursor = conn.execute("""
            INSERT INTO reports (
                image_path, defect_type, confidence,
                latitude, longitude, address, severity,
                priority_score, status, mode, created_at,
                request_hash, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "",
            defect_type,
            float(confidence),
            float(latitude),
            float(longitude),
            address,
            int(severity),
            int(priority_score),
            "Новая",
            mode,
            created_at,
            request_hash,
            created_at,
        ))

        report_id = cursor.lastrowid
        image_path = UPLOAD_DIR / f"report_{report_id}.jpg"

        try:
            image_path.write_bytes(image_bytes)

            conn.execute("""
                UPDATE reports
                SET image_path = ?
                WHERE id = ?
            """, (str(image_path), report_id))

            conn.execute("""
                INSERT INTO status_history (
                    report_id, old_status, new_status, changed_at
                )
                VALUES (?, NULL, 'Новая', ?)
            """, (report_id, created_at))

        except Exception:
            conn.execute(
                "DELETE FROM reports WHERE id = ?",
                (report_id,),
            )
            raise

    return report_id, False


def list_reports(sort_by="priority"):
    ordering = {
        "priority": "priority_score DESC, votes_count DESC, id DESC",
        "urgency": "priority_score DESC, votes_count DESC, id DESC",
        "newest": "id DESC",
        "popular": (
            "votes_count DESC, comments_count DESC, "
            "priority_score DESC, id DESC"
        ),
    }.get(sort_by, "priority_score DESC, id DESC")

    with connect() as conn:
        rows = conn.execute(f"""
            SELECT r.*,
                (
                    SELECT COUNT(*) FROM report_votes v
                    WHERE v.report_id = r.id
                ) AS votes_count,
                (
                    SELECT COUNT(*) FROM report_comments c
                    WHERE c.report_id = r.id
                ) AS comments_count
            FROM reports r
            ORDER BY {ordering}
        """).fetchall()

        return [dict(row) for row in rows]


def get_report(report_id):
    with connect() as conn:
        row = conn.execute("""
            SELECT r.*,
                (
                    SELECT COUNT(*) FROM report_votes v
                    WHERE v.report_id = r.id
                ) AS votes_count,
                (
                    SELECT COUNT(*) FROM report_comments c
                    WHERE c.report_id = r.id
                ) AS comments_count
            FROM reports r
            WHERE r.id = ?
        """, (int(report_id),)).fetchone()

        return dict(row) if row else None


def update_status(report_id, status):
    if status not in STATUSES:
        raise ValueError("Неизвестный статус заявки")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with connect() as conn:
        row = conn.execute(
            "SELECT status FROM reports WHERE id = ?",
            (int(report_id),),
        ).fetchone()

        if not row:
            return False

        old_status = row["status"]

        if old_status != status:
            conn.execute("""
                UPDATE reports
                SET status = ?, updated_at = ?
                WHERE id = ?
            """, (status, now, int(report_id)))

            conn.execute("""
                INSERT INTO status_history (
                    report_id, old_status, new_status, changed_at
                )
                VALUES (?, ?, ?, ?)
            """, (
                int(report_id),
                old_status,
                status,
                now,
            ))

    return True


def add_vote(report_id, voter_token):
    voter_hash = hashlib.sha256(
        str(voter_token).encode("utf-8")
    ).hexdigest()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with connect() as conn:
        exists = conn.execute(
            "SELECT id FROM reports WHERE id = ?",
            (int(report_id),),
        ).fetchone()

        if not exists:
            return False, "Заявка не найдена."

        try:
            conn.execute("""
                INSERT INTO report_votes (
                    report_id, voter_hash, created_at
                )
                VALUES (?, ?, ?)
            """, (int(report_id), voter_hash, now))

        except sqlite3.IntegrityError:
            return False, "Вы уже подтверждали эту заявку."

        count = conn.execute("""
            SELECT COUNT(*) FROM report_votes
            WHERE report_id = ?
        """, (int(report_id),)).fetchone()[0]

        conn.execute("""
            UPDATE reports SET votes_count = ?
            WHERE id = ?
        """, (count, int(report_id)))

    return True, "Спасибо! Заявка подтверждена."


def add_comment(report_id, body, author="Житель"):
    body = (body or "").strip()
    author = (author or "Житель").strip()[:50] or "Житель"

    if not body:
        return False, "Комментарий не может быть пустым."

    if len(body) > 500:
        return False, "Максимум 500 символов."

    now_dt = datetime.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    cutoff = (
        now_dt - timedelta(seconds=60)
    ).strftime("%Y-%m-%d %H:%M:%S")

    with connect() as conn:
        exists = conn.execute(
            "SELECT id FROM reports WHERE id = ?",
            (int(report_id),),
        ).fetchone()

        if not exists:
            return False, "Заявка не найдена."

        duplicate = conn.execute("""
            SELECT id FROM report_comments
            WHERE report_id = ?
              AND body = ?
              AND created_at >= ?
            LIMIT 1
        """, (int(report_id), body, cutoff)).fetchone()

        if duplicate:
            return False, "Такой комментарий недавно уже отправляли."

        conn.execute("""
            INSERT INTO report_comments (
                report_id, author, body, created_at
            )
            VALUES (?, ?, ?, ?)
        """, (int(report_id), author, body, now))

        count = conn.execute("""
            SELECT COUNT(*) FROM report_comments
            WHERE report_id = ?
        """, (int(report_id),)).fetchone()[0]

        conn.execute("""
            UPDATE reports SET comments_count = ?
            WHERE id = ?
        """, (count, int(report_id)))

    return True, "Комментарий опубликован."


def list_comments(report_id):
    with connect() as conn:
        rows = conn.execute("""
            SELECT author, body, created_at
            FROM report_comments
            WHERE report_id = ?
            ORDER BY id DESC
        """, (int(report_id),)).fetchall()

        return [dict(row) for row in rows]


def list_status_history(report_id):
    with connect() as conn:
        rows = conn.execute("""
            SELECT old_status, new_status, changed_at
            FROM status_history
            WHERE report_id = ?
            ORDER BY id DESC
        """, (int(report_id),)).fetchall()

        return [dict(row) for row in rows]


def save_after_photo(report_id, image_bytes):
    path = UPLOAD_DIR / f"report_{int(report_id)}_after.jpg"
    path.write_bytes(image_bytes)

    with connect() as conn:
        exists = conn.execute(
            "SELECT id FROM reports WHERE id = ?",
            (int(report_id),),
        ).fetchone()

        if not exists:
            path.unlink(missing_ok=True)
            return False

        conn.execute("""
            UPDATE reports
            SET after_image_path = ?, updated_at = ?
            WHERE id = ?
        """, (
            str(path),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            int(report_id),
        ))

    return True


def delete_report(report_id):
    with connect() as conn:
        row = conn.execute("""
            SELECT image_path, after_image_path
            FROM reports WHERE id = ?
        """, (int(report_id),)).fetchone()

        if not row:
            return False

        conn.execute(
            "DELETE FROM reports WHERE id = ?",
            (int(report_id),),
        )

    for file_path in (row["image_path"], row["after_image_path"]):
        if file_path:
            try:
                Path(file_path).unlink(missing_ok=True)
            except OSError:
                pass

    return True
