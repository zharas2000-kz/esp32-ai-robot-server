
import os
import time
import logging
import threading

from flask import Flask, request, jsonify, Response
from google import genai
from google.genai import types

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
).strip()

client = genai.Client(api_key=API_KEY) if API_KEY else None

# Последний ответ робота. Для первого теста храним в памяти.
answer_lock = threading.Lock()
latest_answer = {
    "id": 0,
    "answer": "",
    "created_at": 0
}


@app.get("/")
def home():
    return jsonify({
        "status": "online",
        "server": "ESP32 AI Robot",
        "model": MODEL,
        "listen_page": "/listen"
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "ai_key_configured": client is not None,
        "model": MODEL
    })


@app.get("/latest")
def get_latest():
    with answer_lock:
        data = dict(latest_answer)

    response = jsonify(data)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/listen")
def listen_page():
    page = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<title>AI-робот — голосовой ответ</title>
<style>
body {
    font-family: Arial, sans-serif;
    max-width: 600px;
    margin: 0 auto;
    padding: 24px 18px;
    text-align: center;
    background: #f4f6f8;
    color: #20242a;
}
.card {
    background: white;
    border-radius: 18px;
    padding: 24px 18px;
    box-shadow: 0 3px 15px #0001;
}
button {
    width: 100%;
    padding: 16px;
    border: 0;
    border-radius: 12px;
    background: #1769e0;
    color: white;
    font-size: 17px;
    margin-top: 12px;
}
#answer {
    font-size: 19px;
    line-height: 1.5;
    margin-top: 22px;
    overflow-wrap: anywhere;
}
#status {
    color: #536273;
    margin-top: 16px;
}
.small {
    font-size: 14px;
    color: #536273;
    line-height: 1.5;
}
</style>
</head>
<body>
<div class="card">
    <h1>🤖 AI-робот</h1>
    <p>Голосовые ответы в Bluetooth-наушниках</p>

    <button id="start">▶ Запустить прослушивание</button>
    <button id="repeat">🔊 Повторить ответ</button>

    <div id="status">Нажми «Запустить прослушивание»</div>
    <div id="answer">Здесь появится описание предмета.</div>

    <p class="small">
      Сначала подключи Bluetooth-наушники к телефону.
      Не закрывай эту страницу во время работы.
    </p>
</div>

<script>
let running = false;
let lastId = null;
let lastText = "";
let timer = null;

const statusBox = document.getElementById("status");
const answerBox = document.getElementById("answer");

function speak(text) {
    if (!("speechSynthesis" in window)) {
        statusBox.textContent =
            "Этот браузер не поддерживает озвучивание.";
        return;
    }

    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "ru-RU";
    utterance.rate = 0.95;
    utterance.pitch = 1.0;

    const voices = window.speechSynthesis.getVoices();
    const russianVoice = voices.find(
        voice => voice.lang.toLowerCase().startsWith("ru")
    );

    if (russianVoice) {
        utterance.voice = russianVoice;
    }

    utterance.onstart = () => {
        statusBox.textContent = "🔊 Произношу ответ";
    };

    utterance.onend = () => {
        if (running) {
            statusBox.textContent =
                "Слушаю сервер. Жду следующую фотографию…";
        }
    };

    utterance.onerror = (event) => {
        statusBox.textContent =
            "Не удалось озвучить ответ: " + event.error;
    };

    window.speechSynthesis.speak(utterance);
}

async function pollLatest() {
    if (!running) return;

    try {
        const response = await fetch(
            "/latest?t=" + Date.now(),
            { cache: "no-store" }
        );

        if (!response.ok) {
            throw new Error("HTTP " + response.status);
        }

        const data = await response.json();

        if (lastId === null) {
            // Первый запрос только запоминает текущий ответ.
            // Новые ответы после запуска будут озвучиваться.
            lastId = data.id;
            if (data.answer) {
                lastText = data.answer;
                answerBox.textContent = data.answer;
            }
        } else if (data.id > lastId && data.answer) {
            lastId = data.id;
            lastText = data.answer;
            answerBox.textContent = data.answer;
            speak(data.answer);
        }

        if (!window.speechSynthesis.speaking) {
            statusBox.textContent =
                "На связи. Жду новую фотографию…";
        }
    } catch (error) {
        statusBox.textContent =
            "Нет связи с сервером. Повторяю проверку…";
    }
}

document.getElementById("start").addEventListener("click", () => {
    if (running) {
        running = false;
        clearInterval(timer);
        window.speechSynthesis.cancel();
        document.getElementById("start").textContent =
            "▶ Запустить прослушивание";
        statusBox.textContent = "Прослушивание остановлено.";
        return;
    }

    running = true;
    document.getElementById("start").textContent =
        "⏹ Остановить прослушивание";
    statusBox.textContent = "Подключаюсь к серверу…";

    pollLatest();
    timer = setInterval(pollLatest, 2500);
});

document.getElementById("repeat").addEventListener("click", () => {
    if (lastText) {
        speak(lastText);
    } else {
        statusBox.textContent = "Пока нет ответа для повторения.";
    }
});

if ("speechSynthesis" in window) {
    window.speechSynthesis.getVoices();
}
</script>
</body>
</html>
"""
    return Response(page, content_type="text/html; charset=utf-8")


def analyze_image(image_bytes):
    prompt = (
        "Ты голосовой помощник робота. Опиши то, что видно "
        "на фотографии, на русском языке. Ответь понятно, "
        "не более двух предложений. Не выдумывай детали."
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
                    "503", "UNAVAILABLE",
                    "429", "RESOURCE_EXHAUSTED",
                    "500", "INTERNAL",
                    "504", "DEADLINE_EXCEEDED"
                )
            )

            if not temporary or attempt == 2:
                raise

            time.sleep(2 ** attempt)

    raise last_error


@app.post("/vision")
def vision():
    global latest_answer

    if client is None:
        return jsonify({
            "status": "error",
            "error": "GEMINI_API_KEY не настроен в Render"
        }), 503

    image = request.files.get("image")

    if image is None:
        return jsonify({
            "status": "error",
            "error": "Отправьте фотографию в поле image"
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
            "error": "Поддерживается JPEG"
        }), 415

    image_bytes = image.read()

    if not image_bytes:
        return jsonify({
            "status": "error",
            "error": "Получена пустая фотография"
        }), 400

    if not image_bytes.startswith(b"\xff\xd8\xff"):
        return jsonify({
            "status": "error",
            "error": "Файл не является JPEG"
        }), 400

    try:
        answer = analyze_image(image_bytes)

        with answer_lock:
            latest_answer = {
                "id": int(time.time() * 1000),
                "answer": answer,
                "created_at": int(time.time())
            }

        logger.info("Image analyzed successfully")

        return jsonify({
            "status": "success",
            "answer": answer,
            "model": MODEL
        })

    except Exception as exc:
        error_text = str(exc)
        logger.exception("Image analysis failed")

        if any(marker in error_text for marker in ("503", "UNAVAILABLE")):
            return jsonify({
                "status": "error",
                "error": "Gemini временно перегружен. Попробуйте позже."
            }), 503

        if any(marker in error_text for marker in ("429", "RESOURCE_EXHAUSTED")):
            return jsonify({
                "status": "error",
                "error": "Лимит или квота AI исчерпаны."
            }), 429

        return jsonify({
            "status": "error",
            "error": "Ошибка AI. Проверьте Render Logs."
        }), 502


@app.errorhandler(413)
def too_large(error):
    return jsonify({
        "status": "error",
        "error": "Фотография больше 5 МБ"
    }), 413
