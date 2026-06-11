"""
Live Stage Transcription System
Multi-language simultaneous translation
Cross-platform: Mac (afplay) | Windows (pygame) | Linux (mpg123)
Audio plays through local speaker - no phone listener pages
"""
from flask_cors import CORS
from flask import Flask, render_template, Response, jsonify, request, send_file
import os
import io
import re
import sys
import json
import time
import uuid
import queue
import struct
import base64
import platform
import threading
import tempfile
import wave
from dotenv import load_dotenv
load_dotenv()

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("pyaudio not installed. Run: pip install pyaudio")

try:
    import openai as _openai_module
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("openai not installed. Run: pip install openai")

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False
    print("deep_translator not installed. Run: pip install deep-translator")

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False
    print("gTTS not installed. Run: pip install gTTS")

if sys.platform == "win32":
    try:
        import pygame  # pylint: disable=import-error
        PYGAME_AVAILABLE = True
    except ImportError:
        PYGAME_AVAILABLE = False
        print("pygame not installed. Run: pip install pygame")
else:
    PYGAME_AVAILABLE = False

OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
SYSTEM    = platform.system()
AUDIO_DIR = tempfile.gettempdir()
SAMPLE_RATE = 16000
CHUNK_SIZE  = 1024
CHANNELS    = 1

NOISE_PHRASES = [
    "thank you for watching", "thank you for listening",
    "thanks for watching", "thanks for listening",
    "please subscribe", "like and subscribe",
    "subtitles by", "[music]", "[applause]",
    "do not add filler", "transcribe only", "filler words",
    "subscribe only", "only what is spoken",
]
HALLUCINATION_EXACT = {
    "thank you. thank you.", "thanks. thanks.",
    "thank you, thank you.", "thank you! thank you!",
    "thank you. thank you. thank you.",
    "goodbye.", "goodbye", "bye.", "bye",
    "thank you", "thanks", "thank you.",
}

LANGUAGES = {
    "ur":    {"name": "Urdu",       "gtts": "ur",    "label": "Urdu"},
    "ne":    {"name": "Nepali",     "gtts": "ne",    "label": "Nepali"},
    "zh-CN": {"name": "Chinese",    "gtts": "zh-CN", "label": "Chinese"},
    "hi":    {"name": "Hindi",      "gtts": "hi",    "label": "Hindi"},
    "ar":    {"name": "Arabic",     "gtts": "ar",    "label": "Arabic"},
    "es":    {"name": "Spanish",    "gtts": "es",    "label": "Spanish"},
    "fr":    {"name": "French",     "gtts": "fr",    "label": "French"},
    "tr":    {"name": "Turkish",    "gtts": "tr",    "label": "Turkish"},
    "pt":    {"name": "Portuguese", "gtts": "pt",    "label": "Portuguese"},
    "sw":    {"name": "Swahili",    "gtts": "sw",    "label": "Swahili"},
    "pa":    {"name": "Punjabi",    "gtts": "pa",    "label": "Punjabi"},
}

# --- Edit this to change which language plays through the speaker ---
SPEAKER_LANGUAGE = "ur"
# ------------------------------------------------------------------

app = Flask(__name__)
CORS(app)

state = {
    "running":        False,
    "cooldown_until": 0,
    "last_english":   "",
    "history":        [],
    "status":         "idle",
    "error":          None,
    "input_device":   None,
    "speaker_lang":   SPEAKER_LANGUAGE,
}

audio_queue     = queue.Queue()
text_queue      = queue.Queue()

sse_clients = {}
sse_lock    = threading.Lock()


def push_all(event_type, data):
    payload = "data: " + json.dumps({"type": event_type, **data}) + "\n\n"
    with sse_lock:
        for client in sse_clients.values():
            client["queue"].put(payload)


def get_openai():
    if not OPENAI_AVAILABLE:
        raise RuntimeError("openai not installed")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set in .env")
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY)


GLOSSARY_DIR = os.path.dirname(os.path.abspath(__file__))


def glossary_file(lang):
    return os.path.join(GLOSSARY_DIR, "glossary_" + lang + ".json")


def load_glossary(lang="ur"):
    path   = glossary_file(lang)
    legacy = os.path.join(GLOSSARY_DIR, "glossary.json")
    if not os.path.exists(path) and lang == "ur" and os.path.exists(legacy):
        with open(legacy, "r", encoding="utf-8") as f:
            return json.load(f)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_glossary(g, lang="ur"):
    with open(glossary_file(lang), "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, indent=2)


def translate_text(english, lang):
    from deep_translator import GoogleTranslator
    if lang == "ur":
        glossary = load_glossary("ur")
        placeholders = {}
        protected = english
        for i, (eng, urd) in enumerate(sorted(glossary.items(), key=lambda x: -len(x[0]))):
            pattern = re.compile(re.escape(eng), re.IGNORECASE)
            if pattern.search(protected):
                ph = "__TERM" + str(i) + "__"
                placeholders[ph] = urd
                protected = pattern.sub(ph, protected)
        translated = GoogleTranslator(source="en", target="ur").translate(protected)
        for ph, urd in placeholders.items():
            translated = translated.replace(ph, urd)
        return translated.strip()
    return GoogleTranslator(source="en", target=lang).translate(english).strip()


def pcm_to_wav(pcm):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def transcribe(wav_bytes):
    client = get_openai()
    wav_buffer = io.BytesIO(wav_bytes)
    wav_buffer.name = "audio.wav"
    result = client.audio.transcriptions.create(
        model="whisper-1",
        file=wav_buffer,
        response_format="text",
        language="en",
        prompt="",
    )
    return result.strip() if isinstance(result, str) else result.text.strip()


def generate_audio_bytes(text, gtts_code):
    from gtts import gTTS
    buf  = io.BytesIO()
    slow = gtts_code == "ne"
    gTTS(text=text, lang=gtts_code, slow=slow).write_to_fp(buf)
    buf.seek(0)
    return buf.read()


def play_mp3_bytes(mp3_bytes):
    if sys.platform == "darwin":
        import subprocess
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.write(mp3_bytes)
        tmp.flush()
        tmp.close()
        subprocess.run(["afplay", tmp.name], check=True)
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    elif sys.platform == "win32":
        import pygame  # pylint: disable=import-error
        buf = io.BytesIO(mp3_bytes)
        pygame.mixer.init(frequency=22050)
        pygame.mixer.music.load(buf)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.music.stop()
        pygame.mixer.quit()
    else:
        import subprocess
        proc = subprocess.Popen(["mpg123", "-q", "-"], stdin=subprocess.PIPE)
        proc.communicate(input=mp3_bytes)


def is_speech(frame, threshold=600):
    samples = struct.unpack(str(len(frame) // 2) + "h", frame)
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    return rms > threshold


def recording_thread():
    SILENCE_CHUNKS    = 50
    MAX_SECONDS       = 15
    MIN_SPEECH_FRAMES = 8
    pa     = pyaudio.PyAudio()
    kwargs = dict(format=pyaudio.paInt16, channels=CHANNELS,
                  rate=SAMPLE_RATE, input=True, frames_per_buffer=CHUNK_SIZE)
    if state["input_device"] is not None:
        kwargs["input_device_index"] = state["input_device"]
    stream = pa.open(**kwargs)
    print("Recording started (device: " + str(state["input_device"] or "default") + ")")
    try:
        while state["running"]:
            frames, silence_count, speaking = [], 0, False
            max_frames = int(SAMPLE_RATE / CHUNK_SIZE * MAX_SECONDS)
            while state["running"]:
                frame = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                if time.time() < state["cooldown_until"]:
                    continue
                if is_speech(frame):
                    speaking = True
                    frames.append(frame)
                    break
            if not speaking:
                continue
            while state["running"] and len(frames) < max_frames:
                frame = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                frames.append(frame)
                if is_speech(frame):
                    silence_count = 0
                else:
                    silence_count += 1
                    if silence_count >= SILENCE_CHUNKS:
                        break
            if len(frames) >= MIN_SPEECH_FRAMES:
                audio_queue.put(b"".join(frames))
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
        print("Recording stopped")


def transcription_thread():
    print("Transcription thread started")
    while state["running"] or not audio_queue.empty():
        try:
            pcm = audio_queue.get(timeout=2)
        except queue.Empty:
            continue
        try:
            state["status"] = "transcribing"
            push_all("status", {"status": "transcribing"})
            english = transcribe(pcm_to_wav(pcm))
            if not english or len(english) < 2:
                state["status"] = "listening"
                push_all("status", {"status": "listening"})
                continue
            english_norm = english.strip().lower()
            if (
                english_norm in HALLUCINATION_EXACT
                or english_norm.rstrip(".!?, ") in HALLUCINATION_EXACT
            ):
                state["status"] = "listening"
                push_all("status", {"status": "listening"})
                continue
            if any(p in english.lower() for p in NOISE_PHRASES):
                state["status"] = "listening"
                push_all("status", {"status": "listening"})
                continue
            if re.search(r"https?://|www\.|\.( com|org|net|uk|co)", english.lower()):
                print("URL hallucination filtered: " + english[:50])
                state["status"] = "listening"
                push_all("status", {"status": "listening"})
                continue
            curr = english.strip().lower()
            last = state["last_english"].strip().lower()
            if curr == last:
                print("Duplicate skipped: " + english[:40])
                state["status"] = "listening"
                push_all("status", {"status": "listening"})
                continue
            if len(curr) > 10 and len(last) > 10:
                overlap = len(set(curr.split()) & set(last.split()))
                total   = max(len(set(curr.split())), len(set(last.split())))
                if total > 0 and overlap / total > 0.85:
                    print("Near-duplicate skipped: " + english[:40])
                    state["status"] = "listening"
                    push_all("status", {"status": "listening"})
                    continue
            state["last_english"]   = english
            state["cooldown_until"] = time.time() + 3.0
            state["status"] = "translating"
            push_all("status", {"status": "translating"})
            print("Transcribed: " + english[:60])
            text_queue.put(english)
            state["status"] = "listening"
            push_all("status", {"status": "listening"})
        except Exception as e:
            state["error"] = str(e)
            push_all("error", {"message": str(e)})
            state["status"] = "listening"
            time.sleep(1)
    state["status"] = "idle"
    push_all("status", {"status": "idle"})
    print("Transcription thread stopped")


def translation_thread():
    print("Translation thread started")
    while state["running"] or not text_queue.empty():
        try:
            english = text_queue.get(timeout=2)
        except queue.Empty:
            continue
        try:
            lang     = state["speaker_lang"]
            cfg      = LANGUAGES[lang]
            translated = translate_text(english, lang)
            print("[" + cfg["name"] + "] " + translated[:50])
            mp3_bytes  = generate_audio_bytes(translated, cfg["gtts"])
            entry = {
                "english":    english,
                "translated": translated,
                "lang":       lang,
                "lang_name":  cfg["name"],
                "ts":         time.strftime("%H:%M:%S"),
            }
            push_all("transcript", entry)
            # Play on local speaker
            threading.Thread(
                target=play_mp3_bytes,
                args=(mp3_bytes,),
                daemon=True
            ).start()
        except Exception as e:
            print("Translation error: " + str(e))
    print("Translation thread stopped")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/glossary")
def glossary_page():
    return render_template("glossary.html")


@app.route("/stream")
def stream():
    client_id = str(uuid.uuid4())
    q = queue.Queue()
    with sse_lock:
        sse_clients[client_id] = {"queue": q}

    def generate():
        init = {
            "type":   "init",
            "status": state["status"],
            "lang":   state["speaker_lang"],
            "langs":  LANGUAGES,
        }
        yield "data: " + json.dumps(init) + "\n\n"
        try:
            while True:
                try:
                    yield q.get(timeout=30)
                except queue.Empty:
                    yield "data: {\"type\":\"ping\"}\n\n"
        except GeneratorExit:
            pass
        finally:
            with sse_lock:
                sse_clients.pop(client_id, None)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/start", methods=["POST"])
def start():
    if state["running"]:
        return jsonify({"ok": False, "msg": "Already running"})
    if not PYAUDIO_AVAILABLE:
        return jsonify({"ok": False, "msg": "pyaudio not installed"})
    if not OPENAI_API_KEY:
        return jsonify({"ok": False, "msg": "OPENAI_API_KEY missing from .env"})
    state.update({"running": True, "error": None, "last_english": ""})
    while not audio_queue.empty():
        audio_queue.get_nowait()
    while not text_queue.empty():
        text_queue.get_nowait()
    threading.Thread(target=recording_thread,     daemon=True).start()
    threading.Thread(target=transcription_thread, daemon=True).start()
    threading.Thread(target=translation_thread,   daemon=True).start()
    push_all("status", {"status": "listening"})
    return jsonify({"ok": True, "lang": state["speaker_lang"]})


@app.route("/stop", methods=["POST"])
def stop():
    state["running"] = False
    return jsonify({"ok": True})


@app.route("/status")
def get_status():
    return jsonify({
        "running":      state["running"],
        "status":       state["status"],
        "error":        state["error"],
        "speaker_lang": state["speaker_lang"],
    })


@app.route("/api/languages")
def get_languages():
    return jsonify(LANGUAGES)


@app.route("/api/speaker-lang", methods=["POST"])
def set_speaker_lang():
    lang = request.get_json().get("lang", "ur")
    if lang not in LANGUAGES:
        return jsonify({"ok": False, "msg": "Unknown language"})
    state["speaker_lang"] = lang
    push_all("lang_changed", {"lang": lang, "name": LANGUAGES[lang]["name"]})
    print("Speaker language: " + LANGUAGES[lang]["name"])
    return jsonify({"ok": True})


@app.route("/api/devices")
def get_devices():
    if not PYAUDIO_AVAILABLE:
        return jsonify({"devices": [], "current": None})
    pa, devices = pyaudio.PyAudio(), []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["maxInputChannels"] > 0:
            devices.append({"index": i, "name": d["name"],
                            "selected": state["input_device"] == i})
    pa.terminate()
    return jsonify({"devices": devices, "current": state["input_device"]})


@app.route("/api/devices", methods=["POST"])
def set_device():
    state["input_device"] = request.get_json().get("index")
    return jsonify({"ok": True})


@app.route("/api/glossary", methods=["GET"])
def get_glossary():
    lang = request.args.get("lang", "ur")
    return jsonify(load_glossary(lang))


@app.route("/api/glossary", methods=["POST"])
def add_term():
    lang = request.args.get("lang", "ur")
    data = request.get_json()
    en, tr = data.get("english", "").strip(), data.get("urdu", "").strip()
    if not en or not tr:
        return jsonify({"ok": False, "msg": "Both fields required"})
    g = load_glossary(lang)
    g[en] = tr
    save_glossary(g, lang)
    return jsonify({"ok": True})


@app.route("/api/glossary/<path:term>", methods=["DELETE"])
def delete_term(term):
    lang = request.args.get("lang", "ur")
    g = load_glossary(lang)
    if term in g:
        del g[term]
        save_glossary(g, lang)
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "Not found"})


@app.route("/api/glossary/import", methods=["POST"])
def import_glossary():
    lang = request.args.get("lang", "ur")
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"ok": False, "msg": "Invalid format"})
    g = load_glossary(lang)
    g.update(data)
    save_glossary(g, lang)
    return jsonify({"ok": True, "count": len(data), "total": len(g)})


@app.route("/api/pronounce", methods=["POST"])
def pronounce():
    body      = request.get_json()
    text      = body.get("text", body.get("urdu", "")).strip()
    lang_code = body.get("lang", "ur")
    if not text:
        return ("No text", 400)
    try:
        from gtts import gTTS
        gtts_code = LANGUAGES.get(lang_code, {}).get("gtts", "ur")
        tts = gTTS(text=text, lang=gtts_code)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return Response(buf.read(), mimetype="audio/mpeg")
    except Exception as e:
        return (str(e), 500)


if __name__ == "__main__":
    print("Live Stage Transcription System")
    print("-" * 42)
    print("Platform : " + SYSTEM)
    print("pyaudio  : " + ("OK" if PYAUDIO_AVAILABLE else "MISSING - pip install pyaudio"))
    print("openai   : " + ("OK" if OPENAI_AVAILABLE else "MISSING - pip install openai"))
    print(
        "transltr : "
        + ("OK" if TRANSLATOR_AVAILABLE else "MISSING - pip install deep-translator")
    )
    print("gTTS     : " + ("OK" if GTTS_AVAILABLE else "MISSING - pip install gTTS"))
    if sys.platform == "win32":
        print("pygame   : " + ("OK" if PYGAME_AVAILABLE else "MISSING - pip install pygame"))
    print("API key  : " + ("SET" if OPENAI_API_KEY else "NOT SET - check .env file"))
    print("Language : " + LANGUAGES.get(SPEAKER_LANGUAGE, {}).get("name", "?"))
    print("-" * 42)
    print("Control  : http://localhost:5050")
    print("-" * 42)
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)