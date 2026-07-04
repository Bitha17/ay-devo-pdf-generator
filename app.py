import os
import io
import re
import hmac
from datetime import datetime, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from markupsafe import Markup, escape

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_file, send_from_directory, abort, flash,
)
from werkzeug.utils import secure_filename

from parser import parse_txt_file
from pdf import generate_pdf, generate_pdf_from_data
from content import make_slug, extract_title, parse_id_date
import db

# Secrets come from the environment (set them in the WSGI file on PythonAnywhere).
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")

# Refuse to start with missing or known-default secrets, so an insecure config
# can never reach production. For local dev just pass non-default values, e.g.
#   ADMIN_PASSWORD=test123 SECRET_KEY=dev-only python app.py
_INSECURE = {"", "changeme", "dev-secret-change-me"}
if ADMIN_PASSWORD in _INSECURE or SECRET_KEY in _INSECURE:
    raise RuntimeError(
        "Refusing to start: set ADMIN_PASSWORD and SECRET_KEY to non-default "
        "values (see DEPLOY.md). Generate a key with: "
        "python3 -c \"import secrets; print(secrets.token_hex(32))\""
    )

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Publish times are entered in this timezone, stored/compared in UTC.
LOCAL_TZ = ZoneInfo(os.environ.get("DEVO_TZ", "Asia/Jakarta"))

FIXED_BG = "static/bg.png"            # bundled default later-pages background
ACTIVE_BG = os.path.join(db.DATA_DIR, "bg.png")  # admin-uploaded override (persisted)


# ---------------------------------------------------------------- helpers
def require_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def to_local(iso_utc):
    """UTC ISO string -> aware datetime in LOCAL_TZ for display."""
    return datetime.fromisoformat(iso_utc).astimezone(LOCAL_TZ)


def _delete_file(path):
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def current_bg_path():
    """Active content-page background: the admin-uploaded one if present, else
    the bundled default. Always returns an absolute path."""
    return ACTIVE_BG if os.path.exists(ACTIVE_BG) else os.path.join(BASE_DIR, FIXED_BG)


def regenerate_all_pdfs():
    """Re-render every devotion's PDF with the current background. Returns count."""
    bg = current_bg_path()
    count = 0
    for dev in db.list_all():
        cover = dev["image_path"] or os.path.join(BASE_DIR, FIXED_BG)
        pdf_path = dev["pdf_path"] or os.path.join(db.PDF_DIR, f"{dev['slug']}.pdf")
        buffer, _ = generate_pdf_from_data(dev["data"], cover, bg)
        with open(pdf_path, "wb") as f:
            f.write(buffer.getvalue())
        count += 1
    return count


def is_published(dev):
    return datetime.fromisoformat(dev["publish_at"]) <= datetime.now(timezone.utc)


def active_day_index(dev):
    """Index of the day matching today (WIB); 0 if today isn't in this week."""
    today = datetime.now(LOCAL_TZ).date()
    for i, day in enumerate(dev["data"]["days"]):
        if parse_id_date(day.get("date")) == today:
            return i
    return 0


def pick_current(published):
    """From published devotions (already sorted newest week first), pick the one
    whose week contains today (WIB); otherwise the most recent week."""
    today = datetime.now(LOCAL_TZ).date()
    for dev in published:
        days = dev["data"]["days"]
        start = parse_id_date(days[0].get("date")) if days else None
        end = parse_id_date(days[-1].get("date")) if days else None
        if start and end and start <= today <= end:
            return dev
    return published[0] if published else None


app.jinja_env.globals.update(to_local=to_local, is_published=is_published)


# The devotion text carries reportlab-style inline markup (<b>, <i>, …) that the
# PDF renders. Escape everything, then re-allow only a small whitelist of inline
# formatting tags so the web view shows bold/italic without opening an XSS hole.
_ALLOWED_MARKUP = re.compile(
    r"&lt;(/?)(br|strong|em|b|i|u)\s*(/?)&gt;", re.IGNORECASE
)


@app.template_filter("markup")
def markup_filter(text):
    out = _ALLOWED_MARKUP.sub(
        lambda m: "<%s%s%s>" % (m.group(1), m.group(2).lower(), m.group(3)),
        str(escape(text or "")),
    )
    return Markup(out)


# ------------------------------------------------------- brand assets
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@app.route("/assets/icons/<path:name>")
def asset_icon(name):
    return send_from_directory(os.path.join(BASE_DIR, "icons"), name)


@app.route("/assets/fonts/<path:name>")
def asset_font(name):
    return send_from_directory(os.path.join(BASE_DIR, "fonts"), name)


# ---------------------------------------------------------------- reader
@app.route("/")
def index():
    published = db.list_published()
    dev = pick_current(published)
    if not dev:
        return render_template("empty.html")
    return render_template(
        "reader.html", dev=dev, archive=published, is_latest=True,
        active_index=active_day_index(dev),
    )


@app.route("/d/<slug>")
def devotion(slug):
    # Admins can preview scheduled (not-yet-published) devotions.
    dev = db.get_by_slug(slug, include_unpublished=session.get("admin"))
    if not dev:
        abort(404)
    return render_template(
        "reader.html", dev=dev, archive=db.list_published(), is_latest=False,
        active_index=active_day_index(dev),
    )


@app.route("/archive")
def archive():
    return render_template("archive.html", archive=db.list_published())


@app.route("/d/<slug>/hero")
def devotion_hero(slug):
    admin = session.get("admin")
    dev = db.get_by_slug(slug, include_unpublished=admin)
    if not dev or not dev.get("hero_path") or not os.path.exists(dev["hero_path"]):
        abort(404)
    return send_file(dev["hero_path"])


@app.route("/d/<slug>/pdf")
def devotion_pdf(slug):
    admin = session.get("admin")
    dev = db.get_by_slug(slug, include_unpublished=admin)
    if not dev or not dev.get("pdf_path") or not os.path.exists(dev["pdf_path"]):
        abort(404)
    return send_file(dev["pdf_path"], mimetype="application/pdf")


# ---------------------------------------------------------------- admin
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(request.args.get("next") or url_for("admin"))
        flash("Wrong password.")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.route("/admin")
@require_admin
def admin():
    return render_template("admin.html", devotions=db.list_all())


@app.route("/admin/upload", methods=["POST"])
@require_admin
def admin_upload():
    txt_file = request.files["txt"]
    pdf_cover = request.files.get("pdf_cover")   # mandatory: PDF first page
    web_hero = request.files.get("web_hero")     # optional: web title banner
    publish_local = request.form.get("publish_at", "").strip()

    # Persist uploads to disk.
    txt_path = os.path.join(db.UPLOAD_DIR, secure_filename(txt_file.filename))
    txt_file.save(txt_path)

    parsed = parse_txt_file(txt_path)
    slug = make_slug(parsed["week"], parsed["month"])

    # Title: use the admin's override if given, else derive it from the text.
    title = request.form.get("title", "").strip()
    if not title:
        with open(txt_path, encoding="utf-8-sig") as f:
            title = extract_title(f.read())

    # PDF cover (mandatory) — the PDF's first-page background.
    image_path = None
    if pdf_cover and pdf_cover.filename:
        image_path = os.path.join(db.UPLOAD_DIR, f"{slug}_cover_" + secure_filename(pdf_cover.filename))
        pdf_cover.save(image_path)
    cover_for_pdf = image_path or os.path.join(BASE_DIR, FIXED_BG)

    # Web hero banner (optional) — shown in the title box; text hero if absent.
    hero_path = None
    if web_hero and web_hero.filename:
        hero_path = os.path.join(db.UPLOAD_DIR, f"{slug}_hero_" + secure_filename(web_hero.filename))
        web_hero.save(hero_path)

    # Generate the PDF once, at publish time, and store it on disk.
    pdf_buffer, pdf_name = generate_pdf(txt_path, cover_for_pdf, current_bg_path())
    pdf_path = os.path.join(db.PDF_DIR, f"{slug}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_buffer.getvalue())

    # Interpret the entered time as LOCAL_TZ; default to now if blank.
    if publish_local:
        publish_at = datetime.fromisoformat(publish_local).replace(tzinfo=LOCAL_TZ)
    else:
        publish_at = datetime.now(timezone.utc)

    db.upsert_devotion(
        slug=slug, title=title, week=parsed["week"], month=parsed["month"],
        period=parsed["period"], publish_at_utc=publish_at, parsed=parsed,
        pdf_path=pdf_path, image_path=image_path, hero_path=hero_path,
    )

    # The .txt was only needed to parse + render; drop it now.
    try:
        os.remove(txt_path)
    except OSError:
        pass
    flash(f"Saved “{title or slug}” → publishes {to_local(publish_at.astimezone(timezone.utc).isoformat()):%d %b %Y, %H:%M} WIB")
    return redirect(url_for("admin"))


@app.route("/admin/edit/<slug>")
@require_admin
def admin_edit(slug):
    dev = db.get_by_slug(slug, include_unpublished=True)
    if not dev:
        abort(404)
    publish_local = to_local(dev["publish_at"]).strftime("%Y-%m-%dT%H:%M")
    return render_template("admin_edit.html", dev=dev, publish_local=publish_local)


@app.route("/admin/edit/<slug>", methods=["POST"])
@require_admin
def admin_edit_save(slug):
    dev = db.get_by_slug(slug, include_unpublished=True)
    if not dev:
        abort(404)

    parsed = dev["data"]
    image_path = dev["image_path"]
    hero_path = dev["hero_path"]
    week, month, period = dev["week"], dev["month"], dev["period"]
    regen_pdf = False

    # Replace devotion text -> re-parse + regenerate PDF (slug stays the same).
    txt_file = request.files.get("txt")
    if txt_file and txt_file.filename:
        txt_path = os.path.join(db.UPLOAD_DIR, f"{slug}_edit_" + secure_filename(txt_file.filename))
        txt_file.save(txt_path)
        parsed = parse_txt_file(txt_path)
        week, month, period = parsed["week"], parsed["month"], parsed["period"]
        _delete_file(txt_path)  # only needed to parse; PDF regenerates from data
        regen_pdf = True

    # Replace PDF cover -> regenerate PDF.
    cover_file = request.files.get("pdf_cover")
    if cover_file and cover_file.filename:
        if image_path:
            _delete_file(image_path)
        image_path = os.path.join(db.UPLOAD_DIR, f"{slug}_cover_" + secure_filename(cover_file.filename))
        cover_file.save(image_path)
        regen_pdf = True

    # Replace or remove the web banner.
    hero_file = request.files.get("web_hero")
    if hero_file and hero_file.filename:
        _delete_file(hero_path)
        hero_path = os.path.join(db.UPLOAD_DIR, f"{slug}_hero_" + secure_filename(hero_file.filename))
        hero_file.save(hero_path)
    elif request.form.get("remove_hero"):
        _delete_file(hero_path)
        hero_path = None

    title = request.form.get("title", dev["title"]).strip()

    # Publish time (WIB); blank keeps the existing time.
    publish_local = request.form.get("publish_at", "").strip()
    if publish_local:
        publish_at = datetime.fromisoformat(publish_local).replace(tzinfo=LOCAL_TZ)
    else:
        publish_at = datetime.fromisoformat(dev["publish_at"])

    # Regenerate the PDF from canonical data only when text or cover changed.
    pdf_path = dev["pdf_path"] or os.path.join(db.PDF_DIR, f"{slug}.pdf")
    if regen_pdf:
        cover_for_pdf = image_path or os.path.join(BASE_DIR, FIXED_BG)
        buffer, _ = generate_pdf_from_data(parsed, cover_for_pdf, current_bg_path())
        with open(pdf_path, "wb") as f:
            f.write(buffer.getvalue())

    db.upsert_devotion(
        slug=slug, title=title, week=week, month=month, period=period,
        publish_at_utc=publish_at, parsed=parsed, pdf_path=pdf_path,
        image_path=image_path, hero_path=hero_path,
    )
    flash(f"Updated “{title or slug}”.")
    return redirect(url_for("admin"))


@app.route("/admin/delete/<slug>", methods=["POST"])
@require_admin
def admin_delete(slug):
    db.delete_by_slug(slug)
    flash(f"Deleted {slug}.")
    return redirect(url_for("admin"))


@app.route("/admin/download/<slug>")
@require_admin
def admin_download(slug):
    """Download the PDF with the proper 'Devotion AbbaYouth_<period>.pdf' name."""
    dev = db.get_by_slug(slug, include_unpublished=True)
    if not dev or not dev.get("pdf_path") or not os.path.exists(dev["pdf_path"]):
        abort(404)
    return send_file(
        dev["pdf_path"], mimetype="application/pdf", as_attachment=True,
        download_name=f"Devotion AbbaYouth_{dev['period']}.pdf",
    )


@app.route("/admin/background", methods=["POST"])
@require_admin
def admin_background():
    """Replace the content-page background. Affects FUTURE PDFs only; existing
    PDFs are kept as they are (use /admin/regenerate to update them)."""
    bg = request.files.get("bg")
    if not bg or not bg.filename:
        flash("No background image selected.")
        return redirect(url_for("admin"))
    bg.save(ACTIVE_BG)
    flash("Background updated — new PDFs will use it. Existing PDFs are unchanged.")
    return redirect(url_for("admin"))


@app.route("/admin/regenerate", methods=["POST"])
@require_admin
def admin_regenerate():
    """Re-render every existing PDF with the current background (opt-in)."""
    n = regenerate_all_pdfs()
    flash(f"Regenerated {n} PDF(s) with the current background.")
    return redirect(url_for("admin"))


@app.route("/admin/background/current")
@require_admin
def admin_background_current():
    return send_file(current_bg_path())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
