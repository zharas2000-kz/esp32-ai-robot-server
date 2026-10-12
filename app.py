import io
import os
import time
import logging
from flask import Flask, request, jsonify, Response
from google import genai
from google.genai import types
from gtts import gTTS

app = Flask(__name__)

# Максимальный размер фотографии: 5 МБ
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-2.5-flash-lite"
).strip()

client = genai.Client(api_key=API_KEY) if API_KEY else None

latest_audio_data = None


@app.get("/")
def home():
    return jsonify({
        "status": "online",
        "server": "ESP32 AI Museum Robot Server",
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
    prompt = (
        "Ты — аудио-гид и помощник для незрячего посетителя музея. "
        "Твоя задача — по присланной фотографии описать объект искусства или экспонат, перед которым находится пользователь. "
        "Правила ответа:\n"
        "1. Пиши только на русском языке.\n"
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
            logger.warning("Gemini attempt %d/3 failed: %s", attempt + 1, error_text[:300])
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise last_error


# Новый простой эндпоинт для ESP32 (принимает чистые байты JPEG в теле запроса)
@app.post("/vision_raw")
def vision_raw():
    global latest_audio_data

    if client is None:
        return jsonify({"status": "error", "error": "Нет API ключа Gemini"}), 503

    image_bytes = request.data

    if not image_bytes:
        return jsonify({"status": "error", "error": "Пустые данные"}), 400

    if not image_bytes.startswith(b"\xff\xd8\xff"):
        return jsonify({"status": "error", "error": "Неверный формат JPEG"}), 400

    try:
        answer = analyze_image(image_bytes)
        logger.info("Raw image analyzed successfully; text: %s", answer)

        tts = gTTS(text=answer, lang='ru', slow=False)
        audio_fp = io.BytesIO()
        tts.write_to_fp(audio_fp)
        audio_fp.seek(0)
        latest_audio_data = audio_fp.read()

        return jsonify({
            "status": "success",
            "text": answer
        }), 200

    except Exception as exc:
        logger.exception("Raw image analysis failed")
        return jsonify({"status": "error", "error": "Внутренняя ошибка обработки"}), 502


@app.get("/latest-audio")
def latest_audio():
    global latest_audio_data
    if latest_audio_data is None:
        return "", 404
    return Response(latest_audio_data, mimetype="audio/mpeg")


@app.errorhandler(413)
def too_large(error):
    return jsonify({"status": "error", "error": "Файл слишком большой"}), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
