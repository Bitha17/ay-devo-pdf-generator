# Project notes — things that aren't obvious from the code alone

This is tacit/decision knowledge from building the writer/lead collaborative
flow and the verse picker. Read this before changing anything in that area —
the code alone won't tell you *why* it's shaped this way, and a few of these
are easy to accidentally "fix" back into a bug.

## App purpose and main entry points

The app manages weekly Christian devotionals from document upload or team
drafting through review, publication, web reading, and PDF distribution.
AY is presented as **AbbaYouth Devotion**; Umum as **Meditasi Firman**.
Public readers do not need an account.

| Purpose | AY | Umum |
| --- | --- | --- |
| Permanent reader link | `/` | `/umum` |
| Specific week's reader | `/d/<slug>` | `/umum/d/<slug>` |
| Published archive | `/archive` | `/umum/archive` |
| Published PDF | `/d/<slug>/pdf` | `/umum/d/<slug>/pdf` |
| Admin content management | `/admin` | `/admin/umum` |

- `/login` is the single login page. Its toggle selects **Contributor** (email
  and password) or **Super admin** (deployment-configured password). The
  old `/admin/login` and `/contrib/login` URLs redirect there for saved links.
  The super-admin alone uses `/admin/contributors` to create, edit, reset,
  move, and remove writer/lead accounts.
- `/contrib` shows either a
  writer's assigned days or a lead's division-specific weekly dashboard.
- Share the permanent reader link in Linktree or another app so it does not
  need changing each week. `pick_current()` prefers a published week containing
  today's local date, otherwise the most recent published week. It does not
  simply choose the last item uploaded.
- The reader selects today's day when present, otherwise the first day.
  It provides day navigation, web/PDF switching, past weeks, and a
  tap-to-read Bible passage sheet. PDF previews use PDF.js from a CDN;
  the page also offers a direct PDF link if inline rendering fails.

## Roles and route boundaries

- There are three effective roles: **super-admin**, **lead**, and **writer**.
  Super-admin is deliberately not a database contributor role: it is the
  deployment-configured emergency/account-management identity. Leads and
  writers authenticate with their own contributor account.
- A lead is the content administrator for their assigned division. AY leads
  may use `/admin` and its PDF upload/edit/download/background controls; Umum
  leads may use `/admin/umum` and its PDF controls. A lead cannot use the
  other division's routes or the contributor account-management page.
- Writers may access only their own assigned drafts. A lead may manage every
  week and draft in their own division. Route handlers must check the week's
  stored division, not just the division value saved in the browser session.
- Account changes take effect on the contributor's next request because the
  session refreshes role and division from SQLite. Removing an account clears
  its effective access. Moving a writer to another division, or changing a
  writer into a lead, unassigns their days but preserves the draft content for
  a lead to reassign.
- Keep AY routes (`/d/<slug>`, `/d/<slug>/pdf`, and hero) confined to AY and
  Umum routes (`/umum/d/<slug>`, `/umum/d/<slug>/pdf`) confined to Umum. Do
  not let a shared slug expose the other division's content.

## Authoring, review, and publication

There are two ways to supply content:

1. **Admin upload:** upload a prepared document using the division's format,
   supply artwork and optional title/publication time, then save. Admin edit
   pages allow later content changes and PDF regeneration.
2. **Collaborative authoring:** a lead creates a seven-day week and assigns
   individual days to writers. Writers save drafts and submit for review;
   leads can edit, approve, or request changes with review notes. Every day
   must be approved before the week can be published through this flow.

- Draft statuses are `unassigned`, `draft`, `submitted`,
  `changes_requested`, and `approved`. An assigned writer can edit only
  while their day is `draft` or `changes_requested`; leads can edit as well.
- Leads can open and edit every day in their division, including drafts that
  have not been submitted. **Save lead edits** leaves the current review
  status intact, so a lead may correct wording and approve without waiting for
  a writer to resubmit.
- Lead feedback is private while saved as a feedback draft. It reaches the
  assigned writer only after the lead clicks **Send feedback to writer** or
  **Request changes**. The latter also returns the day to `changes_requested`.
- Writer forms auto-save changed content every 20 seconds while the page is
  visible. Auto-save does not submit a draft for review and does not alter its
  status; the explicit Submit button remains authoritative.
- Submission requires the day's Bible reference. AY also requires a verse
  for each nonempty reflection question (see the question-shape notes below).
- Collaborative publication requires a PDF cover image. It creates a
  published-content snapshot and records its slug on the draft week;
  publishing that week again reuses the slug. Draft storage and published
  content are separate: saving a draft does not itself refresh the reader.
- AY includes key message, M1, reflection questions, context, Firman Kristus,
  application, M3 (Responsku), and M4 (Langkah). Umum has the simpler theme,
  reading reference, context, Firman Kristus, and questions structure.
- AY's PDF cover, optional web hero banner, and content-page background are
  different assets. Without a web hero the reader displays a text heading.
  The active AY content background is `data/bg.png` if present, otherwise
  `static/bg.png`. The global background/regenerate controls target AY;
  Umum uses its own PDF renderer.

## Scheduling and visibility

- Publication time is entered in `DEVO_TZ` (default `Asia/Jakarta`) and stored
  in UTC. A blank publication time means publish immediately.
- PDFs are generated when content is saved/published, even if its visibility
  is scheduled for later. Reading an existing PDF does not regenerate it.
- Public queries return only content whose `publish_at` has arrived. No cron
  job or background worker is needed: visibility is checked on each request.
- The super-admin and the matching division's lead can preview scheduled
  content through that division's specific-week and PDF routes. Other users
  receive a 404 until its publication time arrives.

## Failure handling

- `DEVO_MAX_UPLOAD_MB` sets the total multipart upload limit (20 MB by
  default). The app presents a 413 page instead of accepting oversized files.
- Uploads are checked for the supported filename extensions before being
  written: AY source `.txt`/`.docx`, Umum source `.docx`, and artwork
  `.png`/`.jpg`/`.jpeg`. Parsing, invalid publication dates, disk writes, and
  PDF rendering return the user to the relevant form with a message; details
  are written to the server log.
- PDF writes use a temporary file followed by `os.replace`, so a failed PDF
  render cannot leave a half-written PDF at the reader-facing path.
- The app supplies user-facing 403, 404, 413, and 500 pages. The 500 handler
  logs the underlying exception and intentionally does not expose it to users.
- SQLite waits up to 10 seconds when another request holds the database lock.
  Draft saves carry a version number: a stale tab cannot overwrite a newer
  writer or lead edit. The writer is asked to reload instead.

## Code and storage map

| File or directory | Responsibility |
| --- | --- |
| `app.py` | Flask routes, sessions, form validation, scheduling, publishing orchestration |
| `db.py` | SQLite access, schema initialization/migration, published content and draft persistence |
| `parser.py` / `parser_umum.py` | Division-specific document parsing |
| `docx_utils.py` | Extract Word paragraphs and formatting |
| `content.py` | Shared Indonesian date, title, and slug helpers |
| `pdf.py` / `pdf_umum.py` | Division-specific PDF generation with ReportLab |
| `templates/` | Server-rendered reader, admin, and contributor pages |
| `static/bible.js` | Reader Bible reference parsing and passage sheet |
| `static/versepicker.js` / `static/bible_books.js` | Contributor verse selection |

- This is a Python Flask app with SQLite and server-rendered HTML/JavaScript.
- `devotions` stores weekly published content as parsed JSON plus publication
  metadata and asset paths; readers do not re-parse the original document.
- `contributors`, `umum_weeks`, and `day_drafts` hold the collaborative flow
  for both divisions despite the historical `umum_weeks` table name.
- Runtime data lives relative to the project directory: `data/devo.db`,
  `data/uploads/`, and `data/pdfs/`, plus optional `data/bg.png`.
  The database includes contributor accounts and drafts, not just publications.
- `data/` is gitignored and created automatically. A code checkout is not
  a backup of content. Some asset paths stored in the database are absolute,
  so moving a deployment to a different directory may require path updates.

## Deployment and operations

`DEPLOY.md` documents a PythonAnywhere deployment. Its examples focus on the
original AY upload flow; the same Flask application also serves Umum and
contributors, with no separate deployment for those routes.

1. Upload or clone the code, for example to
   `/home/<you>/ay-devo-pdf-generator`.
2. Create a Python 3.11 virtual environment and install `requirements.txt`.
3. Add a manually configured PythonAnywhere web app using the same Python
   version and select the virtual environment.
4. In the WSGI configuration, add the project directory to `sys.path`, set
   `ADMIN_PASSWORD`, `SECRET_KEY`, and `DEVO_TZ`, then import
   `from app import app as application`.
5. Reload the web app. Check the public pages and admin/contributor logins;
   inspect the host's error log if startup fails.

- Use non-default credentials; missing or known-default `ADMIN_PASSWORD`
  and `SECRET_KEY` cause startup to fail. Never commit actual deployment
  secrets. Changing `SECRET_KEY` and reloading invalidates existing signed
  session cookies, including contributor sessions.
- Production loads the application through WSGI. The `python app.py` entry
  point runs Flask's development server with debug enabled and is for local
  development.
- After code updates, install any changed dependencies in the configured
  environment and reload. Preserve `data/` across updates, and back it up
  before updates involving schema changes; initialization can migrate the DB.
- Back up the entire `data/` directory, including the database, uploaded
  artwork, PDFs, and background override. For a consistent file-copy backup,
  pause writes while copying. Restore with the app stopped, preserve the
  deployment path or adjust stored asset paths, then reload and verify.
- The guide describes PythonAnywhere HTTPS, persistent disk, CPU limits,
  and periodic free-app renewal (it states three months). Those are hosting
  policies, not application guarantees; verify current terms in the hosting
  dashboard when deploying. This note does not confirm a live deployment.
- Bible passage fetching and CDN-hosted PDF.js require reader/writer browser
  internet access independently of the Flask application's availability.

## The two divisions

- **AY** and **Umum** share one `devotions` table (`division` column) and one
  `contributors`/`umum_weeks`/`day_drafts` schema, but they are NOT symmetric.
- Original publishing paths (unchanged, still work): AY via `.txt`/`.docx`
  upload at `/admin` (field-label format: `THEME:`, `Ayat Bacaan:`, `M1:`,
  `Key Message:`, `Pertanyaan Perenungan Ayat:`, `Segment 1:`/`Segment 2:`,
  `Aplikasi:`, `M3:`/`M4:`); Umum via `.docx` upload at `/admin/umum` (two
  supported day-header styles — see `parser_umum.py`'s own docstring).
- Newer collaborative flow (writers draft, leads approve, then publish) works
  for **both** divisions now, built on top of the same upload pipeline —
  publishing from the contrib flow calls the exact same
  `generate_pdf_from_data` / `generate_pdf_from_data_umum` +
  `db.upsert_devotion` that a manual upload does. There is no third rendering
  path.

## Week start day — easy to get backwards

- **Umum weeks start Monday** (Senin→Minggu order).
- **AY weeks start Sunday** (Minggu→Sabtu order) — confirmed by `admin.html`'s
  own AY docx format guide, which lists "Minggu" as the first day in its
  example. This was actually gotten wrong once during development (assumed
  Monday for both) and had to be corrected.
- Enforced server-side in `contrib_week_new()` (`app.py`) by division; the
  date `<input>` in `contrib_lead.html` auto-snaps to the correct weekday via
  JS (`TARGET_DAY`), but that's just UX — the server check is authoritative.

## The `questions` field shape

- In `day_drafts`, a question is `{"text": ..., "verse": ...}`, stored as
  `questions_json`. `db._normalize_questions()` also accepts legacy plain
  strings (wraps them with `verse: ""`) so old rows keep loading.
- **Per-question mandatory verse picker is AY-only** ("Pertanyaan Perenungan
  Ayat" is specifically an AY concept). Umum's Pertanyaan is a plain
  one-question-per-line textarea with no verse requirement. `contrib_day()`
  in `app.py` branches on `division` for both the form field it reads
  (`q_text`/`q_verse` vs. `questions_plain`) and the submit-time validation.
  Do not "simplify" this back to one shared code path — it was deliberately
  split apart after being unified once and then de-scoped from Umum.
- At **publish time** (`contrib_week_publish`), each question's `text` +
  `verse` are combined into one plain string (`"text (verse)"` or just
  `"text"` if no verse) because `pdf.py`, `pdf_umum.py`, `reader.html`, and
  `reader_umum.html` all expect `questions` as a flat list of strings — they
  were never changed to understand the `{text, verse}` shape. If you ever
  need the verse rendered separately downstream, that's the conversion point
  to change, not the storage shape.
- `aplikasi` (AY-only) is a plain list of strings — no verse, no picker.

## The verse picker

- `static/versepicker.js` + `static/bible_books.js` (hardcoded 66-book
  chapter counts — standard, doesn't need updating) power a Book → Chapter →
  tick-the-actual-verses widget. It fetches chapter text live from
  `https://bible.sonnylab.com/` (same API `static/bible.js` uses for the
  reader's tap-to-read sheet) — **requires internet access**, no offline
  fallback, no API key.
- A picker holds one or more **passage rows** ("+ Tambah bagian ayat lain"),
  each independently removable, so a reference can span multiple
  chapters/books. They're joined with `"; "` into the final string (e.g.
  `"Mazmur 96:1-9; Yohanes 3:16"`) — this exact semicolon-joined format is
  what `bible.js`'s reader-side `parseRefs()` already expects for the
  tap-to-read sheet. Don't change the separator without checking `bible.js`.
- `BOOK_TOKEN` (the handful of books whose sonnylab API name isn't just the
  plain Indonesian name) is **duplicated** between `bible.js` and
  `versepicker.js` — there was no shared module to put it in without a
  bundler. If sonnylab ever changes a book token, update both files.

## Access control — session precedence

- The shared login page clears a contributor session when super-admin login
  succeeds, and clears the super-admin flag when contributor login succeeds.
  This prevents normal use from holding two identities in one browser.
- `require_lead()` and `contrib_day()` still make a logged-in contributor's
  stored role authoritative if an old session somehow contains both flags.
  A writer must never receive lead controls from an admin flag. Keep this
  rule in `require_lead()` and `contrib_day()` aligned if either is changed.

## Slugs

- Umum: always `umum-<start_date iso>` (`make_slug_umum`), whether published
  via `.docx` upload or the contrib flow.
- AY via `.txt`/`.docx` upload: `make_slug(week, month)` — derived from the
  parsed week/month label text (e.g. `"Week 4"` + `"Januari 2026"`).
- AY via the contrib flow: `f"ay-{start_date.isoformat()}"` — a different,
  ad hoc scheme, because a lead-created week has no "Week N" label to derive
  from. **These two AY slugging schemes are independent** — nothing stops an
  admin-uploaded AY week and a contrib-published AY week from landing on
  visually-similar-but-different slugs for the same calendar week. Not
  currently deduplicated.

## Local dev gotchas (learned the hard way this session)

- **Never `rm -rf data/` while the dev server is running.** `db.py` only
  creates `data/`, `data/uploads/`, `data/pdfs/` once at import time; if the
  directory disappears out from under a running process, every DB query
  starts throwing `sqlite3.OperationalError: unable to open database file`
  until the process is restarted. This actually happened once during
  testing and wiped the user's local test data.
- Port 5000 is commonly taken by macOS's AirPlay Receiver / ControlCenter —
  use a different port locally (e.g. `PORT=5050`).
- The app refuses to start unless `ADMIN_PASSWORD` and `SECRET_KEY` are set
  to non-default values (see `DEPLOY.md`) — this applies locally too.
- **Any JS date math must build ISO date strings from local date parts, never
  `.toISOString()`.** `toISOString()` serializes in UTC; for any timezone
  ahead of UTC (WIB is UTC+7), a local midnight Monday comes out as the
  previous day (Sunday) once serialized. This exact bug silently broke the
  week-start-date picker once — grep for `toISOString` before adding new
  date-handling JS anywhere in this app.

## Schema migration note

- `umum_weeks` originally had `UNIQUE(start_date)` alone (Umum-only, before
  AY support existed). Once AY and Umum could both have a week starting on
  the same calendar date, that constraint would wrongly collide. SQLite
  can't alter a constraint in place, so `db.init_db()` detects the old shape
  (missing `division` column) and recreates the table with
  `UNIQUE(division, start_date)`, copying existing rows across as `division
  = 'umum'`. This migration runs automatically and only once per DB file —
  if you ever need another schema change like this, the recreate-and-copy
  pattern in `init_db()` is the template to follow (SQLite has no
  `ALTER TABLE ... DROP CONSTRAINT`).

## Known gaps (not implemented)

- No notifications (email/push) to writers or leads on status change — they
  have to check `/contrib` themselves.
- No password-reset flow for contributors; the admin has to remove and
  re-add them.
- No draft version history — saving overwrites the previous draft content;
  `review_notes` + `updated_at` are the only trace of prior review activity.
- No dedup/guard against the two independent AY slug schemes colliding (see
  above).
