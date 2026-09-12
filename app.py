import os
import io
import re
import hmac
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from zoneinfo import ZoneInfo

from markupsafe import Markup, escape

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_file, send_from_directory, abort, flash,
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from parser import parse_txt_file, parse_docx_paragraphs as parse_ay_docx_paragraphs
from parser_umum import parse_docx_file
from pdf import generate_pdf_from_data
from pdf_umum import generate_pdf_from_data_umum
from content import (
    make_slug, make_slug_umum, extract_title, parse_id_date,
    DAY_NAMES_ID, format_id_date, format_period, ID_MONTHS_NAME,
)
from docx_utils import extract_docx_paragraphs
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


def require_contributor(view):
    """Any signed-in contributor (writer or lead)."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("contrib_id"):
            return redirect(url_for("contrib_login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def require_lead(view):
    """Lead contributor, or — only when no contributor is logged in at all —
    the super-admin stepping in directly. A logged-in contributor's own role
    always governs, even if this browser also happens to hold an admin
    session (e.g. the same person used /admin earlier): a writer must never
    get lead access just because an old admin cookie is still set."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("contrib_id"):
            if session.get("contrib_role") == "lead":
                return view(*args, **kwargs)
            abort(403)
        if session.get("admin"):
            return view(*args, **kwargs)
        return redirect(url_for("contrib_login", next=request.path))
    return wrapper


def current_contributor():
    cid = session.get("contrib_id")
    return db.get_contributor(cid) if cid else None


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


# ---------------------------------------------------------------- reader (Umum)
@app.route("/umum")
def index_umum():
    published = db.list_published(division="umum")
    dev = pick_current(published)
    if not dev:
        return render_template("empty_umum.html")
    return render_template(
        "reader_umum.html", dev=dev, archive=published, is_latest=True,
        active_index=active_day_index(dev),
    )


@app.route("/umum/d/<slug>")
def devotion_umum(slug):
    dev = db.get_by_slug(slug, include_unpublished=session.get("admin"))
    if not dev or dev["division"] != "umum":
        abort(404)
    return render_template(
        "reader_umum.html", dev=dev, archive=db.list_published(division="umum"),
        is_latest=False, active_index=active_day_index(dev),
    )


@app.route("/umum/archive")
def archive_umum():
    return render_template("archive_umum.html", archive=db.list_published(division="umum"))


@app.route("/umum/d/<slug>/pdf")
def devotion_umum_pdf(slug):
    admin = session.get("admin")
    dev = db.get_by_slug(slug, include_unpublished=admin)
    if not dev or dev["division"] != "umum" or not dev.get("pdf_path") or not os.path.exists(dev["pdf_path"]):
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

    # .docx: same field-label format, but bold/italic come from real Word
    # formatting instead of literal <b>/<i> tags.
    if txt_path.lower().endswith(".docx"):
        paragraphs = extract_docx_paragraphs(txt_path)
        parsed = parse_ay_docx_paragraphs(paragraphs)
        raw_text = "\n".join(p["plain"] for p in paragraphs)
    else:
        parsed = parse_txt_file(txt_path)
        with open(txt_path, encoding="utf-8-sig") as f:
            raw_text = f.read()

    slug = make_slug(parsed["week"], parsed["month"])

    # Title: use the admin's override if given, else derive it from the text.
    title = request.form.get("title", "").strip()
    if not title:
        title = extract_title(raw_text)

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

    # Generate the PDF once, at publish time, and store it on disk. `parsed`
    # is already parsed above (from either .txt or .docx), so render from
    # that rather than re-parsing the file.
    pdf_buffer, pdf_name = generate_pdf_from_data(parsed, cover_for_pdf, current_bg_path())
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
        if txt_path.lower().endswith(".docx"):
            parsed = parse_ay_docx_paragraphs(extract_docx_paragraphs(txt_path))
        else:
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


# ------------------------------------------------------------ admin (Umum)
@app.route("/admin/umum")
@require_admin
def admin_umum():
    return render_template("admin_umum.html", devotions=db.list_all(division="umum"))


@app.route("/admin/umum/upload", methods=["POST"])
@require_admin
def admin_umum_upload():
    docx_file = request.files["docx"]
    pdf_cover = request.files["pdf_cover"]   # mandatory: PDF first page
    start_date_str = request.form.get("start_date", "").strip()
    publish_local = request.form.get("publish_at", "").strip()
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None

    docx_path = os.path.join(db.UPLOAD_DIR, secure_filename(docx_file.filename))
    docx_file.save(docx_path)

    try:
        parsed = parse_docx_file(docx_path, start_date)
    except ValueError as e:
        _delete_file(docx_path)
        flash(str(e))
        return redirect(url_for("admin_umum"))
    slug = make_slug_umum(date.fromisoformat(parsed["start_date"]))

    title = request.form.get("title", "").strip() or parsed["title"]

    image_path = os.path.join(db.UPLOAD_DIR, f"{slug}_cover_" + secure_filename(pdf_cover.filename))
    pdf_cover.save(image_path)

    pdf_buffer, _ = generate_pdf_from_data_umum(parsed, image_path)
    pdf_path = os.path.join(db.PDF_DIR, f"{slug}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_buffer.getvalue())

    if publish_local:
        publish_at = datetime.fromisoformat(publish_local).replace(tzinfo=LOCAL_TZ)
    else:
        publish_at = datetime.now(timezone.utc)

    db.upsert_devotion(
        slug=slug, title=title, week=parsed["week"], month=parsed["month"],
        period=parsed["period"], publish_at_utc=publish_at, parsed=parsed,
        pdf_path=pdf_path, image_path=image_path, hero_path=None,
        division="umum",
    )

    try:
        os.remove(docx_path)
    except OSError:
        pass
    flash(f"Saved “{title}” → publishes {to_local(publish_at.astimezone(timezone.utc).isoformat()):%d %b %Y, %H:%M} WIB")
    return redirect(url_for("admin_umum"))


@app.route("/admin/umum/edit/<slug>")
@require_admin
def admin_umum_edit(slug):
    dev = db.get_by_slug(slug, include_unpublished=True)
    if not dev or dev["division"] != "umum":
        abort(404)
    publish_local = to_local(dev["publish_at"]).strftime("%Y-%m-%dT%H:%M")
    return render_template("admin_edit_umum.html", dev=dev, publish_local=publish_local)


@app.route("/admin/umum/edit/<slug>", methods=["POST"])
@require_admin
def admin_umum_edit_save(slug):
    dev = db.get_by_slug(slug, include_unpublished=True)
    if not dev or dev["division"] != "umum":
        abort(404)

    parsed = dev["data"]
    image_path = dev["image_path"]
    week, month, period = dev["week"], dev["month"], dev["period"]
    regen_pdf = False

    # A replacement .docx without its own per-day dates needs a start date.
    start_date_str = request.form.get("start_date", "").strip()
    docx_file = request.files.get("docx")
    if docx_file and docx_file.filename:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
        docx_path = os.path.join(db.UPLOAD_DIR, f"{slug}_edit_" + secure_filename(docx_file.filename))
        docx_file.save(docx_path)
        try:
            parsed = parse_docx_file(docx_path, start_date)
        except ValueError as e:
            _delete_file(docx_path)
            flash(str(e))
            return redirect(url_for("admin_umum_edit", slug=slug))
        week, month, period = parsed["week"], parsed["month"], parsed["period"]
        _delete_file(docx_path)
        regen_pdf = True

    cover_file = request.files.get("pdf_cover")
    if cover_file and cover_file.filename:
        if image_path:
            _delete_file(image_path)
        image_path = os.path.join(db.UPLOAD_DIR, f"{slug}_cover_" + secure_filename(cover_file.filename))
        cover_file.save(image_path)
        regen_pdf = True

    title = request.form.get("title", dev["title"]).strip()

    publish_local = request.form.get("publish_at", "").strip()
    if publish_local:
        publish_at = datetime.fromisoformat(publish_local).replace(tzinfo=LOCAL_TZ)
    else:
        publish_at = datetime.fromisoformat(dev["publish_at"])

    pdf_path = dev["pdf_path"] or os.path.join(db.PDF_DIR, f"{slug}.pdf")
    if regen_pdf:
        buffer, _ = generate_pdf_from_data_umum(parsed, image_path)
        with open(pdf_path, "wb") as f:
            f.write(buffer.getvalue())

    db.upsert_devotion(
        slug=slug, title=title, week=week, month=month, period=period,
        publish_at_utc=publish_at, parsed=parsed, pdf_path=pdf_path,
        image_path=image_path, hero_path=None, division="umum",
    )
    flash(f"Updated “{title or slug}”.")
    return redirect(url_for("admin_umum"))


@app.route("/admin/umum/delete/<slug>", methods=["POST"])
@require_admin
def admin_umum_delete(slug):
    db.delete_by_slug(slug)
    flash(f"Deleted {slug}.")
    return redirect(url_for("admin_umum"))


@app.route("/admin/umum/download/<slug>")
@require_admin
def admin_umum_download(slug):
    dev = db.get_by_slug(slug, include_unpublished=True)
    if not dev or dev["division"] != "umum" or not dev.get("pdf_path") or not os.path.exists(dev["pdf_path"]):
        abort(404)
    return send_file(
        dev["pdf_path"], mimetype="application/pdf", as_attachment=True,
        download_name=f"{dev['title']} - Umum - {dev['period']}.pdf",
    )


# ------------------------------------------------ contributors (writers/leads)
@app.route("/admin/contributors")
@require_admin
def admin_contributors():
    division = request.args.get("division", "umum")
    if division not in ("ay", "umum"):
        division = "umum"
    return render_template(
        "admin_contributors.html", contributors=db.list_contributors(division), division=division,
    )


@app.route("/admin/contributors/add", methods=["POST"])
@require_admin
def admin_contributors_add():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    role = request.form.get("role", "").strip()
    division = request.form.get("division", "").strip()
    password = request.form.get("password", "")
    if (not name or not email or role not in ("writer", "lead")
            or division not in ("ay", "umum") or len(password) < 6):
        flash("Fill in a name, valid email, role, division, and a password of at least 6 characters.")
        return redirect(url_for("admin_contributors", division=division or "umum"))
    if db.get_contributor_by_email(email):
        flash(f"{email} is already a contributor.")
        return redirect(url_for("admin_contributors", division=division))
    db.create_contributor(name, email, generate_password_hash(password), role, division)
    flash(f"Added {name} as a {division.upper()} {role}.")
    return redirect(url_for("admin_contributors", division=division))


@app.route("/admin/contributors/<int:contributor_id>/delete", methods=["POST"])
@require_admin
def admin_contributors_delete(contributor_id):
    contributor = db.get_contributor(contributor_id)
    db.delete_contributor(contributor_id)
    flash("Contributor removed.")
    return redirect(url_for("admin_contributors", division=contributor["division"] if contributor else "umum"))


@app.route("/contrib/login", methods=["GET", "POST"])
def contrib_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        contributor = db.get_contributor_by_email(email)
        if contributor and check_password_hash(contributor["password_hash"], password):
            session["contrib_id"] = contributor["id"]
            session["contrib_role"] = contributor["role"]
            session["contrib_division"] = contributor["division"]
            return redirect(request.args.get("next") or url_for("contrib_dashboard"))
        flash("Wrong email or password.")
    return render_template("contrib_login.html")


@app.route("/contrib/logout")
def contrib_logout():
    session.pop("contrib_id", None)
    session.pop("contrib_role", None)
    session.pop("contrib_division", None)
    return redirect(url_for("contrib_login"))


@app.route("/contrib")
@require_contributor
def contrib_dashboard():
    me = current_contributor()
    division = session.get("contrib_division", "umum")
    if session.get("contrib_role") == "lead":
        weeks = db.list_weeks(division)
        for w in weeks:
            w["days"] = db.list_day_drafts(w["id"])
        return render_template(
            "contrib_lead.html", me=me, weeks=weeks, division=division,
            writers=[c for c in db.list_contributors(division) if c["role"] == "writer"],
        )
    days = db.list_assigned_drafts(me["id"])
    return render_template("contrib_writer.html", me=me, days=days, division=division)


@app.route("/contrib/weeks/new", methods=["POST"])
@require_lead
def contrib_week_new():
    division = session.get("contrib_division", "umum")
    start_str = request.form.get("start_date", "").strip()
    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
    except ValueError:
        flash("Pick a valid start date.")
        return redirect(url_for("contrib_dashboard"))
    # Umum weeks run Senin->Minggu (start on a Monday); AY weeks run
    # Minggu->Sabtu (start on a Sunday) — matching how each division's own
    # source docs are laid out (see admin.html's AY format guide).
    if division == "ay":
        if start_date.weekday() != 6:
            flash("AY weeks always start on a Sunday — pick a Sunday date.")
            return redirect(url_for("contrib_dashboard"))
        day_names = ["Minggu"] + DAY_NAMES_ID[:-1]
    else:
        if start_date.weekday() != 0:
            flash("Umum weeks always start on a Monday — pick a Monday date.")
            return redirect(url_for("contrib_dashboard"))
        day_names = DAY_NAMES_ID
    day_specs = [
        (name, format_id_date(start_date + timedelta(days=i), name))
        for i, name in enumerate(day_names)
    ]
    week_id = db.create_week(start_date, day_specs, division)
    flash("New week created — assign writers to each day.")
    return redirect(url_for("contrib_week", week_id=week_id))


@app.route("/contrib/weeks/<int:week_id>")
@require_lead
def contrib_week(week_id):
    week = db.get_week(week_id)
    if not week:
        abort(404)
    days = db.list_day_drafts(week_id)
    writers = [c for c in db.list_contributors(week["division"]) if c["role"] == "writer"]
    contributors_by_id = {c["id"]: c for c in db.list_contributors(week["division"])}
    return render_template(
        "contrib_week.html", week=week, days=days, writers=writers,
        contributors_by_id=contributors_by_id,
    )


@app.route("/contrib/day/<int:draft_id>/assign", methods=["POST"])
@require_lead
def contrib_day_assign(draft_id):
    draft = db.get_day_draft(draft_id)
    if not draft:
        abort(404)
    writer_id = request.form.get("writer_id", "").strip()
    db.assign_draft(draft_id, int(writer_id) if writer_id else None)
    return redirect(url_for("contrib_week", week_id=draft["week_id"]))


@app.route("/contrib/day/<int:draft_id>", methods=["GET", "POST"])
@require_contributor
def contrib_day(draft_id):
    draft = db.get_day_draft(draft_id)
    if not draft:
        abort(404)
    week = db.get_week(draft["week_id"])
    division = week["division"]
    me = current_contributor()
    # A logged-in contributor's own role governs, even if this browser also
    # holds an admin session — never let a stale admin cookie grant a writer
    # lead controls (see require_lead for the same rule on other routes).
    if session.get("contrib_id"):
        is_lead = session.get("contrib_role") == "lead"
    else:
        is_lead = bool(session.get("admin"))
    is_owner = draft["assigned_to"] == (me["id"] if me else None)
    if not is_lead and not is_owner:
        abort(403)

    writer_can_edit = is_owner and draft["status"] in ("draft", "changes_requested")

    if request.method == "POST":
        action = request.form.get("action")

        if action in ("save", "submit") and (writer_can_edit or is_lead):
            verse = request.form.get("verse", "").strip()

            # Pertanyaan needs its own chosen verse per question only for AY
            # ("Pertanyaan Perenungan Ayat"); Umum's Pertanyaan is plain text.
            if division == "ay":
                texts = request.form.getlist("q_text")
                verses = request.form.getlist("q_verse")
                questions = []
                for text, q_verse in zip(texts, verses):
                    text, q_verse = text.strip(), q_verse.strip()
                    if text or q_verse:
                        questions.append({"text": text, "verse": q_verse})
            else:
                questions = [
                    {"text": line.strip(), "verse": ""}
                    for line in request.form.get("questions_plain", "").splitlines()
                    if line.strip()
                ]
            aplikasi = [a.strip() for a in request.form.get("aplikasi", "").splitlines() if a.strip()]

            if action == "submit":
                if not verse:
                    flash("Choose the day's reference verse before submitting.")
                    return redirect(url_for("contrib_day", draft_id=draft_id))
                if division == "ay":
                    missing = [q for q in questions if q["text"] and not q["verse"]]
                    if missing:
                        flash("Choose a reference verse for every Pertanyaan before submitting.")
                        return redirect(url_for("contrib_day", draft_id=draft_id))

            new_status = "submitted" if action == "submit" else draft["status"]
            if new_status == "unassigned":
                new_status = "draft"
            db.save_draft_content(
                draft_id,
                theme=request.form.get("theme", "").strip(),
                verse=verse,
                context=request.form.get("context", "").strip(),
                firman_kristus=request.form.get("firman_kristus", "").strip(),
                questions=questions,
                status=new_status,
                key_message=request.form.get("key_message", "").strip() if division == "ay" else "",
                m1=request.form.get("m1", "").strip() if division == "ay" else "",
                m3=request.form.get("m3", "").strip() if division == "ay" else "",
                m4=request.form.get("m4", "").strip() if division == "ay" else "",
                aplikasi=aplikasi if division == "ay" else [],
            )
            flash("Submitted for review." if action == "submit" else "Draft saved.")

        elif action == "approve" and is_lead:
            db.review_draft(draft_id, "approved", "")
            flash(f"Approved {draft['day_name']}.")

        elif action == "request_changes" and is_lead:
            notes = request.form.get("review_notes", "").strip()
            db.review_draft(draft_id, "changes_requested", notes)
            flash(f"Sent {draft['day_name']} back for changes.")

        else:
            abort(403)

        return redirect(url_for("contrib_day", draft_id=draft_id))

    return render_template(
        "contrib_day.html", draft=draft, is_lead=is_lead, division=division,
        writer_can_edit=is_lead or writer_can_edit,
    )


@app.route("/contrib/weeks/<int:week_id>/publish", methods=["GET", "POST"])
@require_lead
def contrib_week_publish(week_id):
    week = db.get_week(week_id)
    if not week:
        abort(404)
    days = db.list_day_drafts(week_id)
    division = week["division"]

    if request.method == "POST":
        if any(d["status"] != "approved" for d in days):
            flash("Every day must be approved before publishing.")
            return redirect(url_for("contrib_week", week_id=week_id))

        pdf_cover = request.files.get("pdf_cover")
        if not pdf_cover or not pdf_cover.filename:
            flash("A PDF cover image is required to publish.")
            return redirect(url_for("contrib_week_publish", week_id=week_id))

        start_date = date.fromisoformat(week["start_date"])
        end_date = start_date + timedelta(days=len(days) - 1)
        title = request.form.get("title", "").strip()
        formatted_questions = [
            [f"{q['text']} ({q['verse']})" if q["verse"] else q["text"] for q in d["questions"]]
            for d in days
        ]

        if division == "ay":
            parsed = {
                "title": title,
                "week": f"Week {start_date.isocalendar()[1]}",
                "month": f"{ID_MONTHS_NAME[start_date.month]} {start_date.year}",
                "period": format_period(start_date, end_date),
                "days": [
                    {
                        "date": d["date_str"], "author": "", "theme": d["theme"], "verse": d["verse"],
                        "key_message": d["key_message"], "context": d["context"],
                        "firman_kristus": d["firman_kristus"], "m1": d["m1"], "m3": d["m3"], "m4": d["m4"],
                        "questions": formatted_questions[i], "aplikasi": d["aplikasi"],
                    }
                    for i, d in enumerate(days)
                ],
            }
            slug = week["published_slug"] or f"ay-{start_date.isoformat()}"
        else:
            parsed = {
                "title": title, "week": "",
                "month": f"{ID_MONTHS_NAME[start_date.month]} {start_date.year}",
                "period": format_period(start_date, end_date),
                "days": [
                    {
                        "date": d["date_str"], "theme": d["theme"], "verse": d["verse"],
                        "context": d["context"], "firman_kristus": d["firman_kristus"],
                        "questions": formatted_questions[i],
                    }
                    for i, d in enumerate(days)
                ],
                "start_date": week["start_date"],
            }
            slug = week["published_slug"] or make_slug_umum(start_date)

        image_path = os.path.join(db.UPLOAD_DIR, f"{slug}_cover_" + secure_filename(pdf_cover.filename))
        pdf_cover.save(image_path)

        if division == "ay":
            pdf_buffer, _ = generate_pdf_from_data(parsed, image_path, current_bg_path())
        else:
            pdf_buffer, _ = generate_pdf_from_data_umum(parsed, image_path)
        pdf_path = os.path.join(db.PDF_DIR, f"{slug}.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_buffer.getvalue())

        publish_local = request.form.get("publish_at", "").strip()
        if publish_local:
            publish_at = datetime.fromisoformat(publish_local).replace(tzinfo=LOCAL_TZ)
        else:
            publish_at = datetime.now(timezone.utc)

        db.upsert_devotion(
            slug=slug, title=parsed["title"], week=parsed["week"], month=parsed["month"],
            period=parsed["period"], publish_at_utc=publish_at, parsed=parsed,
            pdf_path=pdf_path, image_path=image_path, hero_path=None, division=division,
        )
        db.mark_week_published(week_id, slug)
        flash(f"Published “{parsed['title'] or slug}”.")
        return redirect(url_for("contrib_dashboard"))

    return render_template("contrib_publish.html", week=week, days=days)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
