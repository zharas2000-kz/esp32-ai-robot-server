import os
from flask import Flask, request, jsonify

app = Flask(__name__)

# Максимальный размер фотографии — 5 МБ
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


@app.get("/")
def home():
    return jsonify({
        "status": "online",
        "server": "ESP32 AI Robot",
        "message": "Сервер работает"
    })


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/vision")
def vision():
    image = request.files.get("image")

    if image is None:
        return jsonify({
            "error": "Отправьте JPEG в поле image"
        }), 400

    if image.mimetype not in ("image/jpeg", "image/jpg"):
        return jsonify({
            "error": "Поддерживается только JPEG"
        }), 415

    image_bytes = image.read()

    if not image_bytes:
        return jsonify({"error": "Пустое изображение"}), 400

    # Следующий этап: передать image_bytes в AI
    return jsonify({
        "status": "received",
        "bytes": len(image_bytes),
        "answer": "Фотография получена. AI-анализ пока не подключён."
    })


@app.errorhandler(413)
def too_large(error):
    return jsonify({"error": "Фотография больше 5 МБ"}), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
