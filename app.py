import os
import time
import logging

from flask import Flask, request, jsonify
from google import genai
from google.genai import types

app = Flask(__name__)

# Максимальный размер фотографии: 5 МБ
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ключ задаётся в Render -> Environment
API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Можно изменить модель в настройках Render
MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
).strip()

client = genai.Client(api_key=API_KEY) if API_KEY else None


@app.get("/")
def home():
    return jsonify({
        "status": "online",
        "server": "ESP32 AI Robot",
        "ai": "Gemini",
        "model": MODEL
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "ai_key_configured": client is not None,
        "model": MODEL
    })


def analyze_image(image_bytes):
    """Отправляет фотографию Gemini с повторными попытками."""

    prompt = (
        "Ты — голосовой помощник робота. "
        "Опиши, что видно на фотографии, на русском языке. "
        "Ответь простыми словами, максимум двумя предложениями. "
        "Не выдумывай детали, которых нельзя увидеть."
    )

    last_error = None

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type="image/jpeg"
                    ),
                    prompt
                ]
            )

            answer = (response.text or "").strip()

            if not answer:
                raise ValueError("Gemini вернул пустой ответ")

            return answer

        except Exception as exc:
            last_error = exc
            error_text = str(exc)
            logger.warning(
                "Gemini attempt %d/3 failed: %s: %s",
                attempt + 1,
                type(exc).__name__,
                error_text[:500]
            )

            # Повторяем только временные ошибки сервера,
            # перегрузку и ограничения частоты запросов.
            temporary = any(
                marker in error_text
                for marker in (
                    "503",
                    "UNAVAILABLE",
                    "429",
                    "RESOURCE_EXHAUSTED",
                    "500",
                    "INTERNAL",
                    "504",
                    "DEADLINE_EXCEEDED"
                )
            )

            if not temporary or attempt == 2:
                raise

            time.sleep(2 ** attempt)

    raise last_error


@app.post("/vision")
def vision():
    if client is None:
        return jsonify({
            "status": "error",
            "error": "Добавьте GEMINI_API_KEY в Render Environment"
        }), 503

    image = request.files.get("image")

    if image is None:
        return jsonify({
            "status": "error",
            "error": "Нет фотографии. Отправьте файл в поле image."
        }), 400

    # Принимаем JPEG, в том числе если устройство отправляет
    # файл как application/octet-stream.
    content_type = (image.mimetype or "").lower()
    filename = (image.filename or "").lower()

    if (
        content_type not in (
            "image/jpeg",
            "image/jpg",
            "application/octet-stream"
        )
        and not filename.endswith((".jpg", ".jpeg"))
    ):
        return jsonify({
            "status": "error",
            "error": "Поддерживается фотография JPEG."
        }), 415

    image_bytes = image.read()

    if not image_bytes:
        return jsonify({
            "status": "error",
            "error": "Получена пустая фотография."
        }), 400

    # Проверяем сигнатуру JPEG
    if not image_bytes.startswith(b"\xff\xd8\xff"):
        return jsonify({
            "status": "error",
            "error": "Файл не похож на изображение JPEG."
        }), 400

    try:
        answer = analyze_image(image_bytes)

        logger.info(
            "Image analyzed successfully; bytes=%d",
            len(image_bytes)
        )

        return jsonify({
            "status": "success",
            "answer": answer,
            "model": MODEL
        })

    except Exception as exc:
        error_text = str(exc)
        logger.exception("Image analysis failed")

        # Сообщаем клиенту, если модель перегружена.
        if any(
            marker in error_text
            for marker in ("503", "UNAVAILABLE")
        ):
            return jsonify({
                "status": "error",
                "error": (
                    "Модель AI временно перегружена. "
                    "Попробуйте позже."
                )
            }), 503

        if any(
            marker in error_text
            for marker in ("429", "RESOURCE_EXHAUSTED")
        ):
            return jsonify({
                "status": "error",
                "error": (
                    "Превышен лимит запросов или квота AI. "
                    "Проверьте ограничения API."
                )
            }), 429

        return jsonify({
            "status": "error",
            "error": (
                "Не удалось распознать изображение. "
                "Проверьте логи Render."
            )
        }), 502


@app.errorhandler(413)
def too_large(error):
    return jsonify({
        "status": "error",
        "error": "Фотография превышает лимит 5 МБ."
    }), 413


@app.errorhandler(500)
def internal_error(error):
    logger.exception("Internal server error")
    return jsonify({
        "status": "error",
        "error": "Внутренняя ошибка сервера."
    }), 500
