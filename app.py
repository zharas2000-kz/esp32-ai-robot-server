import os
import time
import logging
from flask import Flask, request, jsonify
from google import genai
from google.genai import types

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

logging.basicConfig(level=logging.INFO)

API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY) if API_KEY else None

MODEL = "gemini-3.8-flash"


@app.get("/")
def home():
    return jsonify({
        "status": "online",
        "server": "ESP32 AI Robot",
        "ai": "Gemini"
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "ai_key_configured": client is not None
    })

def ask_gemini(image_bytes):
    last_error = None

    for attempt in range(3):
        try:
            return client.models.generate_content(
                model=MODEL,
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type="image/jpeg"
                    ),
                    (
                        "Опиши изображение на русском языке. "
                        "Ответь кратко, одним-двумя предложениями. "
                        "Не выдумывай детали."
                    )
                ]
            )
        except Exception as e:
            last_error = e
            logging.warning(
                "Попытка Gemini %s не удалась: %s",
                attempt + 1, e
            )

            if attempt < 2:
                time.sleep(2 ** attempt)

    raise last_error
    
@app.post("/vision")
def vision():
    if client is None:
        return jsonify({
            "error": "GEMINI_API_KEY не настроен в Render"
        }), 503

    image = request.files.get("image")

    if image is None:
        return jsonify({
            "error": "Отправьте фотографию в поле image"
        }), 400

    if image.mimetype not in ("image/jpeg", "image/jpg"):
        return jsonify({
            "error": "Поддерживается только JPEG"
        }), 415

    image_bytes = image.read()

    if not image_bytes:
        return jsonify({"error": "Пустая фотография"}), 400

    try:
        response = ask_gemini(image_bytes),
                (
                    "Опиши, что изображено на фотографии, "
                    "на русском языке. Ответь понятно и коротко, "
                    "одним или двумя предложениями, чтобы робот "
                    "мог произнести ответ вслух. Не выдумывай "
                    "детали, которых не видно."
                )
            ]
        )

        answer = (response.text or "").strip()

        if not answer:
            return jsonify({
                "error": "AI не вернул текст"
            }), 502

        return jsonify({
            "status": "success",
            "answer": answer
        })

    except Exception:
        logging.exception("Ошибка анализа изображения")
        return jsonify({
            "error": (
                "Не удалось обработать фотографию. "
                "Проверьте квоту, доступность модели и логи Render."
            )
        }), 502


@app.errorhandler(413)
def too_large(error):
    return jsonify({
        "error": "Размер фотографии превышает 5 МБ"
    }), 413
