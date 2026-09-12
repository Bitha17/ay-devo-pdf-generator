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
from datetime import datetime, timezone, date

from content import parse_id_date

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
                created_at    TEXT NOT NULL,   -- UTC ISO-8601
                division      TEXT NOT NULL DEFAULT 'ay'
            )
            """
        )
        # Migrate older DBs that predate hero_path / division.
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(devotions)")]
        if "hero_path" not in cols:
            conn.execute("ALTER TABLE devotions ADD COLUMN hero_path TEXT")
        if "division" not in cols:
            conn.execute("ALTER TABLE devotions ADD COLUMN division TEXT NOT NULL DEFAULT 'ay'")

        # --- Collaborative writing (writers draft days; leads review/approve) ---
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contributors (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL,   -- 'writer' or 'lead'
                division      TEXT NOT NULL DEFAULT 'umum',
                created_at    TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS umum_weeks (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                start_date     TEXT UNIQUE NOT NULL,   -- ISO date of the first day
                created_at     TEXT NOT NULL,
                published_slug TEXT                     -- set once this week is published
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS day_drafts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                week_id        INTEGER NOT NULL REFERENCES umum_weeks(id),
                day_index      INTEGER NOT NULL,
                day_name       TEXT NOT NULL,
                date_str       TEXT NOT NULL,
                assigned_to    INTEGER REFERENCES contributors(id),
                status         TEXT NOT NULL DEFAULT 'unassigned',
                -- unassigned -> draft -> submitted -> approved
                --                              (or) changes_requested -> draft
                theme          TEXT NOT NULL DEFAULT '',
                verse          TEXT NOT NULL DEFAULT '',
                context        TEXT NOT NULL DEFAULT '',
                firman_kristus TEXT NOT NULL DEFAULT '',
                questions_json TEXT NOT NULL DEFAULT '[]',
                review_notes   TEXT NOT NULL DEFAULT '',
                updated_at     TEXT NOT NULL,
                UNIQUE(week_id, day_index)
            )
            """
        )


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    d["data"] = json.loads(d.pop("parsed_json"))
    return d


def week_start(dev):
    """The devotion's first-day date, used for chronological ordering.
    Falls back to the publish time so a row never sorts to the very bottom."""
    days = dev.get("data", {}).get("days") or []
    if days:
        d = parse_id_date(days[0].get("date"))
        if d:
            return d
    return datetime.fromisoformat(dev["publish_at"]).date()


def upsert_devotion(slug, title, week, month, period, publish_at_utc,
                    parsed, pdf_path, image_path, hero_path, division="ay"):
    """Insert or replace a devotion by slug. publish_at_utc is a tz-aware
    datetime; parsed is the dict from parse_txt_file."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO devotions
                (slug, title, week, month, period, publish_at,
                 parsed_json, pdf_path, image_path, hero_path, created_at, division)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title=excluded.title, week=excluded.week, month=excluded.month,
                period=excluded.period, publish_at=excluded.publish_at,
                parsed_json=excluded.parsed_json, pdf_path=excluded.pdf_path,
                image_path=excluded.image_path, hero_path=excluded.hero_path
            """,
            (slug, title, week, month, period,
             publish_at_utc.astimezone(timezone.utc).isoformat(),
             json.dumps(parsed, ensure_ascii=False), pdf_path, image_path,
             hero_path, _now_iso(), division),
        )


def get_latest_published(division="ay"):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM devotions WHERE division = ? AND publish_at <= ? "
            "ORDER BY publish_at DESC LIMIT 1",
            (division, _now_iso()),
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


def list_published(division="ay"):
    """Published devotions, newest week first (by the devotion's own date)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM devotions WHERE division = ? AND publish_at <= ?",
            (division, _now_iso()),
        ).fetchall()
    devs = [_row_to_dict(r) for r in rows]
    devs.sort(key=week_start, reverse=True)
    return devs


def list_all(division="ay"):
    """Admin view: every devotion in a division, newest week first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM devotions WHERE division = ?", (division,)
        ).fetchall()
    devs = [_row_to_dict(r) for r in rows]
    devs.sort(key=week_start, reverse=True)
    return devs


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


# ------------------------------------------------------ contributors (writers/leads)
def create_contributor(name, email, password_hash, role, division="umum"):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO contributors (name, email, password_hash, role, division, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, email.strip().lower(), password_hash, role, division, _now_iso()),
        )


def get_contributor_by_email(email):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM contributors WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    return dict(row) if row else None


def get_contributor(contributor_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM contributors WHERE id = ?", (contributor_id,)
        ).fetchone()
    return dict(row) if row else None


def list_contributors(division="umum"):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM contributors WHERE division = ? ORDER BY role, name",
            (division,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_contributor(contributor_id):
    with _connect() as conn:
        conn.execute(
            "UPDATE day_drafts SET assigned_to = NULL WHERE assigned_to = ?",
            (contributor_id,),
        )
        conn.execute("DELETE FROM contributors WHERE id = ?", (contributor_id,))


# ------------------------------------------------------ umum weeks & day drafts
def create_week(start_date, day_specs):
    """day_specs: list of (day_name, date_str) in order. Creates the week and
    one unassigned day_draft per entry. Returns the new week's id."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO umum_weeks (start_date, created_at) VALUES (?, ?)",
            (start_date.isoformat(), _now_iso()),
        )
        week_id = cur.lastrowid
        for i, (day_name, date_str) in enumerate(day_specs):
            conn.execute(
                "INSERT INTO day_drafts (week_id, day_index, day_name, date_str, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (week_id, i, day_name, date_str, _now_iso()),
            )
    return week_id


def list_weeks():
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM umum_weeks ORDER BY start_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_week(week_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM umum_weeks WHERE id = ?", (week_id,)
        ).fetchone()
    return dict(row) if row else None


def mark_week_published(week_id, slug):
    with _connect() as conn:
        conn.execute(
            "UPDATE umum_weeks SET published_slug = ? WHERE id = ?", (slug, week_id)
        )


def _normalize_questions(raw_list):
    """Each question is {"text", "verse"} — a chosen reference is mandatory
    going forward. Older rows saved before that requirement may still hold
    plain strings; wrap those with an empty verse so old drafts still load."""
    out = []
    for q in raw_list:
        if isinstance(q, dict):
            out.append({"text": q.get("text", ""), "verse": q.get("verse", "")})
        else:
            out.append({"text": q, "verse": ""})
    return out


def list_day_drafts(week_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM day_drafts WHERE week_id = ? ORDER BY day_index", (week_id,)
        ).fetchall()
    days = [dict(r) for r in rows]
    for d in days:
        d["questions"] = _normalize_questions(json.loads(d.pop("questions_json")))
    return days


def get_day_draft(draft_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM day_drafts WHERE id = ?", (draft_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["questions"] = _normalize_questions(json.loads(d.pop("questions_json")))
    return d


def list_assigned_drafts(contributor_id):
    """Every day_draft assigned to this writer, most recent week first."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT day_drafts.*, umum_weeks.start_date AS week_start
            FROM day_drafts JOIN umum_weeks ON umum_weeks.id = day_drafts.week_id
            WHERE assigned_to = ?
            ORDER BY umum_weeks.start_date DESC, day_index
            """,
            (contributor_id,),
        ).fetchall()
    days = [dict(r) for r in rows]
    for d in days:
        d["questions"] = _normalize_questions(json.loads(d.pop("questions_json")))
    return days


def assign_draft(draft_id, contributor_id):
    with _connect() as conn:
        conn.execute(
            "UPDATE day_drafts SET assigned_to = ?, status = "
            "CASE WHEN status = 'unassigned' THEN 'draft' ELSE status END WHERE id = ?",
            (contributor_id or None, draft_id),
        )


def save_draft_content(draft_id, theme, verse, context, firman_kristus, questions, status):
    with _connect() as conn:
        conn.execute(
            """
            UPDATE day_drafts SET theme=?, verse=?, context=?, firman_kristus=?,
                questions_json=?, status=?, updated_at=?
            WHERE id = ?
            """,
            (theme, verse, context, firman_kristus, json.dumps(questions, ensure_ascii=False),
             status, _now_iso(), draft_id),
        )


def review_draft(draft_id, status, review_notes=""):
    with _connect() as conn:
        conn.execute(
            "UPDATE day_drafts SET status = ?, review_notes = ?, updated_at = ? WHERE id = ?",
            (status, review_notes, _now_iso(), draft_id),
        )


init_db()
