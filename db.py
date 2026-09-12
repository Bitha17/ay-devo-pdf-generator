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
import hashlib
import re
from datetime import datetime, timezone, date
from urllib.parse import urlsplit

from content import parse_id_date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")   # title images
PDF_DIR = os.path.join(DATA_DIR, "pdfs")         # generated PDFs
DB_PATH = os.path.join(DATA_DIR, "devo.db")

for d in (DATA_DIR, UPLOAD_DIR, PDF_DIR):
    os.makedirs(d, exist_ok=True)


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA busy_timeout = 10000")
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
                division       TEXT NOT NULL DEFAULT 'umum',
                start_date     TEXT NOT NULL,   -- ISO date of the first day
                created_at     TEXT NOT NULL,
                published_slug TEXT,             -- set once this week is published
                UNIQUE(division, start_date)
            )
            """
        )
        # Migrate a pre-AY-support DB: it has UNIQUE(start_date) alone (no
        # division column), which would collide once AY and Umum can both
        # have a week starting the same Monday. SQLite can't drop a
        # constraint in place, so recreate the table.
        week_cols = [r["name"] for r in conn.execute("PRAGMA table_info(umum_weeks)")]
        if "division" not in week_cols:
            conn.execute("ALTER TABLE umum_weeks RENAME TO umum_weeks_old")
            conn.execute(
                """
                CREATE TABLE umum_weeks (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    division       TEXT NOT NULL DEFAULT 'umum',
                    start_date     TEXT NOT NULL,
                    created_at     TEXT NOT NULL,
                    published_slug TEXT,
                    UNIQUE(division, start_date)
                )
                """
            )
            conn.execute(
                "INSERT INTO umum_weeks (id, division, start_date, created_at, published_slug) "
                "SELECT id, 'umum', start_date, created_at, published_slug FROM umum_weeks_old"
            )
            conn.execute("DROP TABLE umum_weeks_old")

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
                -- AY-only fields; stay blank/'[]' for Umum days.
                key_message    TEXT NOT NULL DEFAULT '',
                m1             TEXT NOT NULL DEFAULT '',
                m3             TEXT NOT NULL DEFAULT '',
                m4             TEXT NOT NULL DEFAULT '',
                aplikasi_json  TEXT NOT NULL DEFAULT '[]',
                review_notes   TEXT NOT NULL DEFAULT '',
                feedback_draft TEXT NOT NULL DEFAULT '', -- private until lead sends it
                version        INTEGER NOT NULL DEFAULT 1,
                updated_at     TEXT NOT NULL,
                UNIQUE(week_id, day_index)
            )
            """
        )
        draft_cols = [r["name"] for r in conn.execute("PRAGMA table_info(day_drafts)")]
        for col in ("key_message", "m1", "m3", "m4"):
            if col not in draft_cols:
                conn.execute(f"ALTER TABLE day_drafts ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        if "aplikasi_json" not in draft_cols:
            conn.execute("ALTER TABLE day_drafts ADD COLUMN aplikasi_json TEXT NOT NULL DEFAULT '[]'")
        if "feedback_draft" not in draft_cols:
            conn.execute("ALTER TABLE day_drafts ADD COLUMN feedback_draft TEXT NOT NULL DEFAULT ''")
        if "version" not in draft_cols:
            conn.execute("ALTER TABLE day_drafts ADD COLUMN version INTEGER NOT NULL DEFAULT 1")

        # Access-log analytics deliberately retain no raw IP addresses or query
        # strings.  The fingerprint makes repeated imports safe, while the
        # salted visitor token allows approximate unique-visitor counts.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS access_events (
                fingerprint   TEXT PRIMARY KEY,
                occurred_at   TEXT NOT NULL,
                method        TEXT NOT NULL,
                path          TEXT NOT NULL,
                status        INTEGER NOT NULL,
                response_ms   REAL NOT NULL,
                response_size INTEGER NOT NULL,
                visitor_token TEXT NOT NULL,
                is_asset      INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS access_events_time ON access_events(occurred_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS access_events_path ON access_events(path)")


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


def update_contributor(contributor_id, name, email, role, division, password_hash=None):
    """Update a contributor. Returns False when the email belongs to another account.

    An account which stops being a writer or moves division is unassigned from
    its days. Those drafts remain intact for the relevant lead to reassign.
    """
    try:
        with _connect() as conn:
            old = conn.execute(
                "SELECT role, division FROM contributors WHERE id = ?", (contributor_id,)
            ).fetchone()
            if not old:
                return False
            if password_hash:
                conn.execute(
                    "UPDATE contributors SET name = ?, email = ?, role = ?, division = ?, password_hash = ? "
                    "WHERE id = ?",
                    (name, email.strip().lower(), role, division, password_hash, contributor_id),
                )
            else:
                conn.execute(
                    "UPDATE contributors SET name = ?, email = ?, role = ?, division = ? WHERE id = ?",
                    (name, email.strip().lower(), role, division, contributor_id),
                )
            if old["role"] == "writer" and (role != "writer" or old["division"] != division):
                conn.execute("UPDATE day_drafts SET assigned_to = NULL WHERE assigned_to = ?", (contributor_id,))
        return True
    except sqlite3.IntegrityError:
        return False


# ------------------------------------------------------ umum weeks & day drafts
def create_week(start_date, day_specs, division="umum"):
    """day_specs: list of (day_name, date_str) in order. Creates the week and
    one unassigned day_draft per entry. Returns the new week's id."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO umum_weeks (division, start_date, created_at) VALUES (?, ?, ?)",
            (division, start_date.isoformat(), _now_iso()),
        )
        week_id = cur.lastrowid
        for i, (day_name, date_str) in enumerate(day_specs):
            conn.execute(
                "INSERT INTO day_drafts (week_id, day_index, day_name, date_str, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (week_id, i, day_name, date_str, _now_iso()),
            )
    return week_id


def list_weeks(division="umum"):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM umum_weeks WHERE division = ? ORDER BY start_date DESC", (division,)
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


def _hydrate_draft(d):
    d["questions"] = _normalize_questions(json.loads(d.pop("questions_json")))
    d["aplikasi"] = json.loads(d.pop("aplikasi_json"))
    return d


def list_day_drafts(week_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM day_drafts WHERE week_id = ? ORDER BY day_index", (week_id,)
        ).fetchall()
    return [_hydrate_draft(dict(r)) for r in rows]


def get_day_draft(draft_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM day_drafts WHERE id = ?", (draft_id,)).fetchone()
    return _hydrate_draft(dict(row)) if row else None


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
    return [_hydrate_draft(dict(r)) for r in rows]


def assign_draft(draft_id, contributor_id):
    with _connect() as conn:
        conn.execute(
            "UPDATE day_drafts SET assigned_to = ?, status = "
            "CASE WHEN status = 'unassigned' THEN 'draft' ELSE status END WHERE id = ?",
            (contributor_id or None, draft_id),
        )


def save_draft_content(draft_id, theme, verse, context, firman_kristus, questions, status,
                        key_message="", m1="", m3="", m4="", aplikasi=None, expected_version=None):
    """key_message/m1/m3/m4/aplikasi are AY-only fields; left at their
    defaults, an Umum day's row simply keeps them blank."""
    with _connect() as conn:
        query = """
            UPDATE day_drafts SET theme=?, verse=?, context=?, firman_kristus=?,
                questions_json=?, key_message=?, m1=?, m3=?, m4=?, aplikasi_json=?,
                status=?, updated_at=?, version=version+1
            WHERE id = ?
        """
        values = [
            theme, verse, context, firman_kristus, json.dumps(questions, ensure_ascii=False),
            key_message, m1, m3, m4, json.dumps(aplikasi or [], ensure_ascii=False),
            status, _now_iso(), draft_id,
        ]
        if expected_version is not None:
            query += " AND version = ?"
            values.append(expected_version)
        cur = conn.execute(
            query, values,
        )
    return cur.rowcount == 1


def review_draft(draft_id, status, review_notes=""):
    with _connect() as conn:
        conn.execute(
            "UPDATE day_drafts SET status = ?, review_notes = ?, updated_at = ? WHERE id = ?",
            (status, review_notes, _now_iso(), draft_id),
        )


def update_feedback_draft(draft_id, feedback_draft):
    """Store feedback privately until a lead deliberately sends it."""
    with _connect() as conn:
        conn.execute(
            "UPDATE day_drafts SET feedback_draft = ?, updated_at = ? WHERE id = ?",
            (feedback_draft, _now_iso(), draft_id),
        )


def publish_feedback(draft_id, feedback, status=None):
    """Make feedback visible to the assigned writer, optionally requesting changes."""
    with _connect() as conn:
        if status:
            conn.execute(
                "UPDATE day_drafts SET review_notes = ?, feedback_draft = '', status = ?, updated_at = ? WHERE id = ?",
                (feedback, status, _now_iso(), draft_id),
            )
        else:
            conn.execute(
                "UPDATE day_drafts SET review_notes = ?, feedback_draft = '', updated_at = ? WHERE id = ?",
                (feedback, _now_iso(), draft_id),
            )


# ------------------------------------------------------ access-log analytics
_ACCESS_LOG_PATTERN = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<timestamp>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<target>\S+)(?: \S+)?" '
    r'(?P<status>\d{3}) (?P<size>\S+) "[^"]*" "[^"]*" "(?P<forwarded>[^"]*)" '
    r'response-time=(?P<duration>[\d.]+)\s*$'
)


def _access_event_from_line(line, visitor_salt):
    """Parse one PythonAnywhere access-log line without retaining its IP or query.

    ``visitor_salt`` must be private and stable (the application's SECRET_KEY is
    suitable).  The resulting token cannot be used to recover the address.
    """
    match = _ACCESS_LOG_PATTERN.match(line)
    if not match:
        return None
    try:
        timestamp = datetime.strptime(match["timestamp"], "%d/%b/%Y:%H:%M:%S %z")
        path = urlsplit(match["target"]).path or "/"
        forwarded = match["forwarded"].split(",")[0].strip()
        visitor = forwarded or match["ip"]
        return {
            "occurred_at": timestamp.astimezone(timezone.utc).isoformat(),
            "method": match["method"],
            "path": path[:500],
            "status": int(match["status"]),
            "response_ms": round(float(match["duration"]) * 1000, 1),
            "response_size": 0 if match["size"] == "-" else int(match["size"]),
            "visitor_token": hashlib.sha256(
                f"{visitor_salt}:{visitor}".encode("utf-8")
            ).hexdigest()[:16],
            "is_asset": int(path.startswith(("/static/", "/assets/", "/favicon"))),
        }
    except (OverflowError, ValueError):
        return None


def import_access_log(path, visitor_salt):
    """Import a PythonAnywhere access log and return import counts.

    The file may be imported repeatedly; its per-line fingerprint makes the
    operation idempotent.  Invalid or incomplete lines are skipped so a log
    being written while it is read does not break the dashboard.
    """
    imported = skipped = 0
    # A busy browser can make two asset requests with exactly the same log
    # line (including its second-level timestamp). Count repeats in this input
    # so each one is kept; the same ordered log then still imports idempotently.
    occurrences = {}
    with open(path, "r", encoding="utf-8", errors="replace") as log_file, _connect() as conn:
        for line in log_file:
            raw_line = line.rstrip("\n")
            event = _access_event_from_line(raw_line, visitor_salt)
            if not event:
                skipped += 1
                continue
            raw_fingerprint = hashlib.sha256(
                f"{visitor_salt}:{raw_line}".encode("utf-8")
            ).hexdigest()
            occurrences[raw_fingerprint] = occurrences.get(raw_fingerprint, 0) + 1
            event["fingerprint"] = hashlib.sha256(
                f"{raw_fingerprint}:{occurrences[raw_fingerprint]}".encode("utf-8")
            ).hexdigest()
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO access_events
                    (fingerprint, occurred_at, method, path, status, response_ms,
                     response_size, visitor_token, is_asset)
                VALUES (:fingerprint, :occurred_at, :method, :path, :status, :response_ms,
                        :response_size, :visitor_token, :is_asset)
                """,
                event,
            )
            imported += cur.rowcount
    return {"imported": imported, "skipped": skipped}


def access_analytics(days=30):
    """Return privacy-preserving aggregates for the super-admin dashboard."""
    days = max(1, min(int(days), 365))
    cutoff = datetime.now(timezone.utc).replace(microsecond=0).timestamp() - days * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
    with _connect() as conn:
        total = conn.execute(
            """SELECT COUNT(*) AS requests, COUNT(DISTINCT visitor_token) AS visitors,
                      SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS errors,
                      AVG(response_ms) AS average_ms
               FROM access_events WHERE occurred_at >= ? AND is_asset = 0""",
            (cutoff_iso,),
        ).fetchone()
        daily = conn.execute(
            """SELECT substr(occurred_at, 1, 10) AS day, COUNT(*) AS requests,
                      COUNT(DISTINCT visitor_token) AS visitors,
                      SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS errors
               FROM access_events
               WHERE occurred_at >= ? AND is_asset = 0
               GROUP BY day ORDER BY day DESC""",
            (cutoff_iso,),
        ).fetchall()
        top_pages = conn.execute(
            """SELECT path, COUNT(*) AS requests, COUNT(DISTINCT visitor_token) AS visitors
               FROM access_events
               WHERE occurred_at >= ? AND is_asset = 0
               GROUP BY path ORDER BY requests DESC, path LIMIT 10""",
            (cutoff_iso,),
        ).fetchall()
        slow_pages = conn.execute(
            """SELECT path, COUNT(*) AS requests, ROUND(AVG(response_ms), 1) AS average_ms,
                      ROUND(MAX(response_ms), 1) AS max_ms
               FROM access_events
               WHERE occurred_at >= ? AND is_asset = 0
               GROUP BY path HAVING requests >= 2
               ORDER BY average_ms DESC, requests DESC LIMIT 10""",
            (cutoff_iso,),
        ).fetchall()
        errors = conn.execute(
            """SELECT status, path, COUNT(*) AS requests
               FROM access_events
               WHERE occurred_at >= ? AND status >= 400
               GROUP BY status, path ORDER BY requests DESC, status DESC LIMIT 10""",
            (cutoff_iso,),
        ).fetchall()
        recent = conn.execute(
            """SELECT occurred_at, method, path, status, response_ms, visitor_token
               FROM access_events WHERE occurred_at >= ? AND is_asset = 0
               ORDER BY occurred_at DESC LIMIT 20""",
            (cutoff_iso,),
        ).fetchall()
        bounds = conn.execute(
            "SELECT MIN(occurred_at) AS first_event, MAX(occurred_at) AS last_event, COUNT(*) AS stored FROM access_events"
        ).fetchone()
    return {
        "summary": dict(total), "daily": [dict(row) for row in daily],
        "top_pages": [dict(row) for row in top_pages], "slow_pages": [dict(row) for row in slow_pages],
        "errors": [dict(row) for row in errors], "recent": [dict(row) for row in recent],
        "bounds": dict(bounds),
    }


init_db()
