import os
import time
import logging
import io

from flask import Flask, request, jsonify, send_file
from google import genai
from google.genai import types
from gtts import gTTS

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
        "server": "ESP32 AI Robot with Audio",
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
    """Отправляет фотографию Gemini с повторными попытками для музейного аудио-гида."""

    prompt = (
        "Ты — аудио-гид и помощник для незрячего посетителя музея. "
        "Твоя задача — по присланной фотографии описать объект искусства или экспонат, перед которым находится пользователь. "
        "Правила ответа:\n"
        "1. Пиши только на казахском языке.\n"
        "2. Говори кратко, емко и выразительно (так как текст будет озвучиваться в наушники), объемом не более 3-4 предложений.\n"
        "3. Сначала назови объект, затем опиши его визуальные и тактильные свойства: из чего он сделан (металл, дерево, ткань), форму, текстуру, размеры и цвета.\n"
        "4. Расскажи самую интересную историческую или культурную справку об этом экспонате.\n"
        "5. Избегай сложных визуальных терминов без пояснений, делай упор на атмосферу и восприятие."
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

    if not image_bytes.startswith(b"\xff\xd8\xff"):
        return jsonify({
            "status": "error",
            "error": "Файл не похож на изображение JPEG."
        }), 400

    try:
        # 1. Получаем текст от Gemini
        answer = analyze_image(image_bytes)
        logger.info("Image analyzed successfully; text: %s", answer)

        # 2. Превращаем текст в аудио (MP3) с помощью gTTS
        tts = gTTS(text=answer, lang='kk', slow=False)
        audio_fp = io.BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)

        # 3. Отправляем MP3 файл клиенту, а текст записываем в кастомный заголовок
        response = send_file(
            audio_fp,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name="speech.mp3"
        )
        
        # Безопасно кодируем текст для хедера (заменяем не-latin1 символы)
        safe_answer = answer.encode('utf-8', errors='ignore').decode('latin-1', errors='ignore')
        response.headers["X-AI-Answer"] = safe_answer
        return response

    except Exception as exc:
        error_text = str(exc)
        logger.exception("Image analysis failed")

        if any(marker in error_text for marker in ("503", "UNAVAILABLE")):
            return jsonify({"status": "error", "error": "Модель AI временно перегружена."}), 503

        if any(marker in error_text for marker in ("429", "RESOURCE_EXHAUSTED")):
            return jsonify({"status": "error", "error": "Превышен лимит запросов AI."}), 429

        return jsonify({"status": "error", "error": "Внутренняя ошибка при обработке."}), 502


@app.errorhandler(413)
def too_large(error):
    return jsonify({"status": "error", "error": "Фотография превышает лимит 5 МБ."}), 413


@app.errorhandler(500)
def internal_error(error):
    logger.exception("Internal server error")
    return jsonify({"status": "error", "error": "Внутренняя ошибка сервера."}), 500
