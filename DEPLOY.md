# Deploying on PythonAnywhere (free tier)

The app is now a small publishing system: you upload each week's devotion (admin),
and readers always hit ONE stable URL that shows the latest *published* devotion.
Set that link once in Linktree / the mobile app and never change it again.

## URLs
- `/` — latest published devotion (the permanent link to share)
- `/d/<slug>` — a specific week, e.g. `/d/week-4-jan-2026`
- `/archive` — list of past devotions
- `/d/<slug>/pdf` — the PDF ("View as PDF" button)
- `/admin` — upload + schedule (password protected)

## One-time setup on PythonAnywhere

1. **Upload the code.** Push to GitHub and `git clone` in a Bash console, or upload a zip.
   Put it somewhere like `/home/<you>/ay-devo-pdf-generator`.

2. **Virtualenv.** In a Bash console:
   ```
   mkvirtualenv devo --python=python3.11
   pip install -r ay-devo-pdf-generator/requirements.txt
   ```

3. **Web tab → Add a new web app → Manual configuration** (same Python version).

4. **Virtualenv field:** enter `/home/<you>/.virtualenvs/devo`.

5. **WSGI file** (Web tab links to it). Replace its contents with:
   ```python
   import os, sys

   path = "/home/<you>/ay-devo-pdf-generator"
   if path not in sys.path:
       sys.path.insert(0, path)

   os.environ["ADMIN_PASSWORD"] = "your-strong-password"
   os.environ["SECRET_KEY"]     = "some-long-random-string"
   os.environ["DEVO_TZ"]        = "Asia/Jakarta"

   # Optional, but recommended when analytics imports run as a scheduled task.
   # Use the same value in both the web app and importer.
   with open("/home/<you>/.devo-analytics-salt") as f:
       os.environ["DEVO_ANALYTICS_SALT"] = f.read().strip()

   from app import app as application
   ```

   **The app refuses to start** if `ADMIN_PASSWORD` or `SECRET_KEY` is missing or
   left at a default — so you can't accidentally deploy an insecure config (you'll
   see a `RuntimeError` in the error log until both are set). Generate a strong key:
   ```
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
   To force all admin sessions to log out (e.g. after a suspected leak), change
   `SECRET_KEY` to a new value and reload — that invalidates existing cookies.

6. **Reload** the web app (button on the Web tab). Visit `/admin`, log in, upload `input.txt`
   + a title image, set a publish time (WIB), done.

## Important notes for the free tier

- **Server runs in UTC; you enter publish times in WIB.** The app converts for you
  (`DEVO_TZ=Asia/Jakarta`). Times shown in `/admin` are WIB.
- **Persistent storage.** The DB and uploads live in `data/` on disk (PythonAnywhere keeps
  the filesystem between reloads). `data/` is gitignored — it is created automatically.
  Do NOT rely on the old in-memory store; it was removed.
- **No background worker needed.** Scheduled publishing works by comparing `publish_at`
  to the current time on each request — so it "just works" even on the free tier.
- **HTTPS** is provided automatically on `https://<you>.pythonanywhere.com`.
- **3-month expiry:** free apps must be renewed by clicking "Run until 3 months from today"
  on the Web tab periodically, or the site goes offline.
- **CPU seconds** are limited on free tier. PDF generation uses some CPU, but it only runs
  once per upload (not per reader), so this is fine.

## Analytics and preserving access history

The super-admin-only `/admin/analytics` page imports PythonAnywhere access-log
entries into `data/devo.db`. It keeps the request time, route, HTTP status,
response time and a salted anonymous visitor token. It deliberately does not
store IP addresses, query strings, referrers, or browser strings.

PythonAnywhere rotates its live access log, so create a salt file once and add
a daily **Tasks** entry. Replace `<you>` and the virtualenv path as appropriate:

```
umask 077
python3 -c "import secrets; print(secrets.token_hex(32))" > /home/<you>/.devo-analytics-salt
```

```
/home/<you>/.virtualenvs/devo/bin/python /home/<you>/ay-devo-pdf-generator/analytics_import.py
```

The importer can run more than once a day; it ignores already stored lines.
Use the dashboard's **Import latest log** button to verify the path first. The
historical data in SQLite survives PythonAnywhere log rotation, but it cannot
recover events that rotated away before the first import.

## Backups
Everything is in `data/devo.db` + `data/uploads/` + `data/pdfs/`. Download `data/` from the
Files tab to back up; restoring is just putting it back.
