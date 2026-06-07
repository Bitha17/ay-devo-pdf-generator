"""SQLite storage for published devotions.

One row per weekly devotion. Reader-facing queries only return rows whose
publish_at (stored as UTC ISO-8601) is at or before 'now'; admin queries ignore
that so content can be uploaded and previewed in advance.

Files (title image + generated PDF) live on disk under DATA_DIR; the DB stores
their paths plus the parsed devotion JSON so we never re-parse at read time.
"""
import os
import json
import sqlite3
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")   # title images
PDF_DIR = os.path.join(DATA_DIR, "pdfs")         # generated PDFs
DB_PATH = os.path.join(DATA_DIR, "devo.db")

for d in (DATA_DIR, UPLOAD_DIR, PDF_DIR):
    os.makedirs(d, exist_ok=True)


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS devotions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                slug          TEXT UNIQUE NOT NULL,
                title         TEXT,
                week          TEXT,
                month         TEXT,
                period        TEXT,
                publish_at    TEXT NOT NULL,   -- UTC ISO-8601
                parsed_json   TEXT NOT NULL,
                pdf_path      TEXT,            -- absolute path on disk
                image_path    TEXT,            -- PDF cover (mandatory)
                hero_path     TEXT,            -- web hero banner (optional)
                created_at    TEXT NOT NULL    -- UTC ISO-8601
            )
            """
        )
        # Migrate older DBs that predate hero_path.
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(devotions)")]
        if "hero_path" not in cols:
            conn.execute("ALTER TABLE devotions ADD COLUMN hero_path TEXT")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    d["data"] = json.loads(d.pop("parsed_json"))
    return d


def upsert_devotion(slug, title, week, month, period, publish_at_utc,
                    parsed, pdf_path, image_path, hero_path):
    """Insert or replace a devotion by slug. publish_at_utc is a tz-aware
    datetime; parsed is the dict from parse_txt_file."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO devotions
                (slug, title, week, month, period, publish_at,
                 parsed_json, pdf_path, image_path, hero_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title=excluded.title, week=excluded.week, month=excluded.month,
                period=excluded.period, publish_at=excluded.publish_at,
                parsed_json=excluded.parsed_json, pdf_path=excluded.pdf_path,
                image_path=excluded.image_path, hero_path=excluded.hero_path
            """,
            (slug, title, week, month, period,
             publish_at_utc.astimezone(timezone.utc).isoformat(),
             json.dumps(parsed, ensure_ascii=False), pdf_path, image_path,
             hero_path, _now_iso()),
        )


def get_latest_published():
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM devotions WHERE publish_at <= ? "
            "ORDER BY publish_at DESC LIMIT 1",
            (_now_iso(),),
        ).fetchone()
    return _row_to_dict(row)


def get_by_slug(slug, include_unpublished=False):
    with _connect() as conn:
        if include_unpublished:
            row = conn.execute(
                "SELECT * FROM devotions WHERE slug = ?", (slug,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM devotions WHERE slug = ? AND publish_at <= ?",
                (slug, _now_iso()),
            ).fetchone()
    return _row_to_dict(row)


def list_published():
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM devotions WHERE publish_at <= ? "
            "ORDER BY publish_at DESC",
            (_now_iso(),),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_all():
    """Admin view: every devotion, published or scheduled."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM devotions ORDER BY publish_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_by_slug(slug):
    with _connect() as conn:
        row = conn.execute(
            "SELECT pdf_path, image_path, hero_path FROM devotions WHERE slug = ?", (slug,)
        ).fetchone()
        conn.execute("DELETE FROM devotions WHERE slug = ?", (slug,))
    if row:
        for p in (row["pdf_path"], row["image_path"], row["hero_path"]):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


init_db()
