import os
import uuid
import io
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from pdf import generate_pdf

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Temporary in-memory storage
pdf_store = {}

# Fixed background
FIXED_BG = "static/bg.png"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    txt_file = request.files["txt"]
    title_img = request.files["title"]

    # Save uploaded files temporarily
    txt_path = os.path.join(UPLOAD_FOLDER, secure_filename(txt_file.filename))
    title_path = os.path.join(UPLOAD_FOLDER, secure_filename(title_img.filename))

    txt_file.save(txt_path)
    title_img.save(title_path)

    # Generate PDF (in memory)
    pdf_buffer, pdf_path = generate_pdf(txt_path, title_path, FIXED_BG)
    pdf_buffer.seek(0)
    filename = os.path.basename(pdf_path)

    # Store in memory
    pdf_id = str(uuid.uuid4())
    pdf_store[pdf_id] = {
        "data": pdf_buffer.getvalue(),
        "filename": os.path.basename(pdf_path)
    }
    return jsonify({
        "preview_url": f"/preview/{pdf_id}",
        "download_url": f"/download/{pdf_id}",
        "filename": filename
    })


@app.route("/preview/<pdf_id>")
def preview(pdf_id):
    if pdf_id not in pdf_store:
        return "File not found", 404

    return send_file(
        io.BytesIO(pdf_store[pdf_id]["data"]),
        mimetype="application/pdf"
    )

@app.route("/download/<pdf_id>")
def download(pdf_id):
    if pdf_id not in pdf_store:
        return "File not found", 404

    return send_file(
        io.BytesIO(pdf_store[pdf_id]["data"]),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=pdf_store[pdf_id]["filename"]
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)