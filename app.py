import os
from flask import Flask, render_template, request, send_file
from werkzeug.utils import secure_filename
from pdf import generate_pdf

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Fixed background (your "semi-static" image)
FIXED_BG = "static/bg.png"

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    txt_file = request.files["txt"]
    title_img = request.files["title"]

    txt_path = os.path.join(UPLOAD_FOLDER, secure_filename(txt_file.filename))
    title_path = os.path.join(UPLOAD_FOLDER, secure_filename(title_img.filename))

    txt_file.save(txt_path)
    title_img.save(title_path)

    pdf_buffer, pdf_path = generate_pdf(txt_path, title_path, FIXED_BG)

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=pdf_path,
        mimetype="application/pdf"
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)