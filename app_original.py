"""
Live Stage Transcription System
Mic → Whisper (English) → Translate → Spoken in selected language

Single language output — operator selects before starting.
Cross-platform: Mac (afplay) | Windows (winsound) | Linux (mpg123)
"""

import os
import io
import re
import json
import time
import uuid
import queue
import struct
import platform
import threading
import tempfile
import wave
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, Response, jsonify, request
from flask_cors import CORS

# ── Optional imports ──────────────────────────────────────────────────────────
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("⚠ pyaudio not installed.")

try:
    OPENAI_AVAILABLE = True
    import openai as _openai_module
except ImportError:
    OPENAI_AVAILABLE = False
    print("⚠ openai not installed.")

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False
    print("⚠ deep_translator not installed.")

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False
    print("⚠ gTTS not installed.")

# ── Config ────────────────────────────────────────────────────────────────────
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
SYSTEM             = platform.system()
AUDIO_DIR          = tempfile.gettempdir()

SAMPLE_RATE = 16000
CHUNK_SIZE  = 1024
CHANNELS    = 1

NOISE_PHRASES = [
    "thank you for watching", "thank you for listening", "thanks for watching",
    "thanks for listening", "please subscribe", "don't forget to subscribe",
    "like and subscribe", "subtitles by", "[music]", "[applause]",
    "do not add filler", "don't add filler", "do not repeat",
    "transcribe only", "filler words",
]
HALLUCINATION_EXACT = {
    "thank you. thank you.", "thanks. thanks.",
    "thank you, thank you.", "thank you! thank you!",
    "goodbye.", "goodbye", "bye.", "bye",
}

# ── Supported languages ───────────────────────────────────────────────────────
LANGUAGES = {
    "ur":    {"name": "Urdu",       "gtts": "ur",    "label": "اردو"},
    "zh-CN": {"name": "Chinese",    "gtts": "zh-CN", "label": "中文"},
    "ne":    {"name": "Nepali",     "gtts": "ne",    "label": "नेपाली"},
    "hi":    {"name": "Hindi",      "gtts": "hi",    "label": "हिंदी"},
    "ar":    {"name": "Arabic",     "gtts": "ar",    "label": "عربي"},
    "es":    {"name": "Spanish",    "gtts": "es",    "label": "Español"},
    "fr":    {"name": "French",     "gtts": "fr",    "label": "Français"},
    "tr":    {"name": "Turkish",    "gtts": "tr",    "label": "Türkçe"},
    "pt":    {"name": "Portuguese", "gtts": "pt",    "label": "Português"},
    "sw":    {"name": "Swahili",    "gtts": "sw",    "label": "Kiswahili"},
    "pa":    {"name": "Punjabi",    "gtts": "pa",    "label": "ਪੰਜਾਬੀ"},
}

app = Flask(__name__)
CORS(app)

# ── Shared state ──────────────────────────────────────────────────────────────
state = {
    "running":        False,
    "muted":          False,
    "cooldown_until": 0,
    "last_english":   "",
    "history":        [],
    "status":         "idle",
    "error":          None,
    "target_lang":    "ur",
    "input_device":   None,
}

audio_queue    = queue.Queue()
playback_queue = queue.Queue()

# ── SSE ───────────────────────────────────────────────────────────────────────
sse_clients = {}
sse_lock    = threading.Lock()

def push_event(event_type: str, data: dict):
    payload = f"data: {json.dumps({'type': event_type, **data})}\n\n"
    with sse_lock:
        for q in sse_clients.values():
            q.put(payload)

# ── OpenAI ────────────────────────────────────────────────────────────────────
def get_openai():
    if not OPENAI_AVAILABLE:
        raise RuntimeError("openai package not installed")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY)

# ── Glossary ──────────────────────────────────────────────────────────────────
GLOSSARY_DIR = os.path.dirname(__file__)

def glossary_file(lang: str) -> str:
    """Returns path to per-language glossary file."""
    return os.path.join(GLOSSARY_DIR, f"glossary_{lang}.json")

def load_glossary(lang: str = "ur") -> dict:
    # Support legacy glossary.json for Urdu
    path = glossary_file(lang)
    legacy = os.path.join(GLOSSARY_DIR, "glossary.json")
    if not os.path.exists(path) and lang == "ur" and os.path.exists(legacy):
        return json.load(open(legacy, "r", encoding="utf-8"))
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_glossary(g: dict, lang: str = "ur"):
    with open(glossary_file(lang), "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, indent=2)

# ── Translation ───────────────────────────────────────────────────────────────
def translate_text(english: str) -> str:
    from deep_translator import GoogleTranslator
    lang = state["target_lang"]
    if lang == "ur":
        glossary = load_glossary("ur")
        placeholders = {}
        protected = english
        for i, (eng, urd) in enumerate(sorted(glossary.items(), key=lambda x: -len(x[0]))):
            pattern = re.compile(re.escape(eng), re.IGNORECASE)
            if pattern.search(protected):
                ph = f"__TERM{i}__"
                placeholders[ph] = urd
                protected = pattern.sub(ph, protected)
        translated = GoogleTranslator(source='en', target='ur').translate(protected)
        for ph, urd in placeholders.items():
            translated = translated.replace(ph, urd)
        return translated.strip()
    return GoogleTranslator(source='en', target=lang).translate(english).strip()

# ── Transcription ─────────────────────────────────────────────────────────────
def pcm_to_wav(pcm: bytes) -> bytes:
    buf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(buf.name, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    path = buf.name
    with open(path, "rb") as f:
        data = f.read()
    os.unlink(path)
    return data

def transcribe(wav_bytes: bytes) -> str:
    client = get_openai()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(wav_bytes)
    tmp.flush()
    tmp.close()
    try:
        with open(tmp.name, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",
                language="en",
                prompt="Transcribe only what is actually spoken. Do not add filler words or repeat sentences.",
            )
        return result.strip() if isinstance(result, str) else result.text.strip()
    finally:
        os.unlink(tmp.name)

# ── TTS ───────────────────────────────────────────────────────────────────────
def generate_audio(text: str, audio_id: str) -> str:
    from gtts import gTTS
    out_path  = os.path.join(AUDIO_DIR, f"live_{audio_id}.mp3")
    gtts_code = LANGUAGES.get(state["target_lang"], {}).get("gtts", "ur")
    try:
        if ELEVENLABS_API_KEY:
            import requests
            r = requests.post(
                "https://api.elevenlabs.io/v1/text-to-speech/pNInz6obpgDQGcFmaJgB",
                headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
                json={"text": text, "model_id": "eleven_multilingual_v2",
                      "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
            )
            if r.status_code == 200:
                with open(out_path, "wb") as f:
                    f.write(r.content)
                return out_path
        gTTS(text=text, lang=gtts_code).save(out_path)
        print(f"✓ Audio ready [{gtts_code}]: {audio_id}")
        return out_path
    except Exception as e:
        print(f"✗ TTS error: {e}")
        return ""

# ── Playback ──────────────────────────────────────────────────────────────────
def play_audio(path: str):
    import subprocess
    if SYSTEM == "Darwin":
        subprocess.run(["afplay", path], check=True)
    elif SYSTEM == "Windows":
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME)
    else:
        subprocess.run(["mpg123", "-q", path], check=True)

def playback_worker():
    print(f"🔈 Playback worker ready ({SYSTEM})")
    while True:
        try:
            path = playback_queue.get(timeout=2)
        except queue.Empty:
            continue
        if path is None:
            break
        try:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                state["muted"] = True
                state["cooldown_until"] = time.time() + (os.path.getsize(path) / 16000) + 4.0
                play_audio(path)
                time.sleep(1.5)
                state["cooldown_until"] = time.time() + 1.0
                state["muted"] = False
        except Exception as e:
            state["muted"] = False
            print(f"✗ Playback error: {e}")

# ── VAD ───────────────────────────────────────────────────────────────────────
def is_speech(frame: bytes, threshold: int = 400) -> bool:
    samples = struct.unpack(f"{len(frame)//2}h", frame)
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    return rms > threshold

# ── Thread 1: Recorder ────────────────────────────────────────────────────────
def recording_thread():
    SILENCE_CHUNKS    = 40
    MAX_SECONDS       = 15
    MIN_SPEECH_FRAMES = 8

    pa     = pyaudio.PyAudio()
    kwargs = dict(format=pyaudio.paInt16, channels=CHANNELS,
                  rate=SAMPLE_RATE, input=True, frames_per_buffer=CHUNK_SIZE)
    if state["input_device"] is not None:
        kwargs["input_device_index"] = state["input_device"]

    stream = pa.open(**kwargs)
    print(f"🎙 Recording started (device: {state['input_device'] or 'default'})")
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
        print("🎙 Recording stopped")

# ── Thread 2: Processor ───────────────────────────────────────────────────────
def processing_thread():
    print("⚙ Processing thread started")
    while state["running"] or not audio_queue.empty():
        try:
            pcm = audio_queue.get(timeout=2)
        except queue.Empty:
            continue
        try:
            state["status"] = "transcribing"
            push_event("status", {"status": "transcribing"})
            english = transcribe(pcm_to_wav(pcm))

            if not english or len(english) < 2:
                state["status"] = "listening"
                push_event("status", {"status": "listening"})
                continue
            if english.strip().lower().rstrip('.!?,') in HALLUCINATION_EXACT:
                state["status"] = "listening"
                push_event("status", {"status": "listening"})
                continue
            if any(p in english.lower() for p in NOISE_PHRASES):
                state["status"] = "listening"
                push_event("status", {"status": "listening"})
                continue
            if english.strip().lower() == state["last_english"].strip().lower():
                state["status"] = "listening"
                push_event("status", {"status": "listening"})
                continue

            state["last_english"]   = english
            state["cooldown_until"] = time.time() + 2.0

            state["status"] = "translating"
            push_event("status", {"status": "translating"})
            translated = translate_text(english)

            audio_id = str(int(time.time() * 1000))
            entry = {
                "english":  english,
                "urdu":     translated,
                "ts":       time.strftime("%H:%M:%S"),
                "audio_id": audio_id,
                "lang":     state["target_lang"],
                "lang_name": LANGUAGES.get(state["target_lang"], {}).get("name", ""),
            }
            print(f"📝 [{entry['lang_name']}] '{english[:50]}'")
            state["history"].insert(0, entry)
            state["history"] = state["history"][:30]
            push_event("transcript", entry)

            threading.Thread(target=tts_worker, args=(translated, audio_id), daemon=True).start()

            state["status"] = "listening"
            push_event("status", {"status": "listening"})

        except Exception as e:
            state["error"] = str(e)
            push_event("error", {"message": str(e)})
            state["status"] = "listening"
            time.sleep(1)

    state["status"] = "idle"
    push_event("status", {"status": "idle"})
    print("⚙ Processing thread stopped")

# ── Thread 3: TTS worker ──────────────────────────────────────────────────────
def tts_worker(text: str, audio_id: str):
    path = generate_audio(text, audio_id)
    if path and os.path.exists(path):
        playback_queue.put(path)

# ── Flask routes ──────────────────────────────────────────────────────────────
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
        sse_clients[client_id] = q
    def generate():
        yield f"data: {json.dumps({'type':'init','history':state['history'],'status':state['status'],'target_lang':state['target_lang']})}\n\n"
        try:
            while True:
                try:
                    yield q.get(timeout=30)
                except queue.Empty:
                    yield 'data: {"type":"ping"}\n\n'
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
        return jsonify({"ok": False, "msg": "OPENAI_API_KEY missing"})
    state.update({"running": True, "error": None, "last_english": ""})
    while not audio_queue.empty():
        audio_queue.get_nowait()
    threading.Thread(target=recording_thread,  daemon=True).start()
    threading.Thread(target=processing_thread, daemon=True).start()
    push_event("status", {"status": "listening"})
    return jsonify({"ok": True, "lang": state["target_lang"]})

@app.route("/stop", methods=["POST"])
def stop():
    state["running"] = False
    state["muted"]   = False
    while not playback_queue.empty():
        try: playback_queue.get_nowait()
        except: break
    return jsonify({"ok": True})

@app.route("/status")
def get_status():
    return jsonify({
        "running":     state["running"],
        "status":      state["status"],
        "error":       state["error"],
        "target_lang": state["target_lang"],
    })

@app.route("/api/languages")
def get_languages():
    return jsonify(LANGUAGES)

@app.route("/api/language", methods=["POST"])
def set_language():
    lang = request.get_json().get("lang", "ur")
    if lang not in LANGUAGES:
        return jsonify({"ok": False, "msg": f"Unsupported: {lang}"})
    state["target_lang"] = lang
    push_event("lang_changed", {"lang": lang, "name": LANGUAGES[lang]["name"]})
    print(f"🌐 Language → {LANGUAGES[lang]['name']}")
    return jsonify({"ok": True, "name": LANGUAGES[lang]["name"]})

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
    en, tr = data.get("english","").strip(), data.get("urdu","").strip()
    if not en or not tr:
        return jsonify({"ok": False, "msg": "Both fields required"})
    g = load_glossary(lang); g[en] = tr; save_glossary(g, lang)
    return jsonify({"ok": True})

@app.route("/api/glossary/<path:term>", methods=["DELETE"])
def delete_term(term):
    lang = request.args.get("lang", "ur")
    g = load_glossary(lang)
    if term in g:
        del g[term]; save_glossary(g, lang)
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "Term not found"})

@app.route("/api/glossary/<path:term>", methods=["PUT"])
def update_term(term):
    lang = request.args.get("lang", "ur")
    tr = request.get_json().get("urdu","").strip()
    if not tr: return jsonify({"ok": False, "msg": "Required"})
    g = load_glossary(lang); g[term] = tr; save_glossary(g, lang)
    return jsonify({"ok": True})

@app.route("/api/glossary/import", methods=["POST"])
def import_glossary():
    lang = request.args.get("lang", "ur")
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"ok": False, "msg": "Invalid format"})
    g = load_glossary(lang); g.update(data); save_glossary(g, lang)
    return jsonify({"ok": True, "count": len(data), "total": len(g)})

@app.route("/api/pronounce", methods=["POST"])
def pronounce():
    body      = request.get_json()
    text      = body.get("text", body.get("urdu", "")).strip()
    lang_code = body.get("lang", state["target_lang"])
    if not text: return ("No text", 400)
    try:
        from gtts import gTTS
        gtts_code = LANGUAGES.get(lang_code, {}).get("gtts", "ur")
        tts = gTTS(text=text, lang=gtts_code)
        buf = io.BytesIO()
        tts.write_to_fp(buf); buf.seek(0)
        return Response(buf.read(), mimetype="audio/mpeg")
    except Exception as e:
        return (str(e), 500)

@app.route("/audio/<audio_id>", methods=["GET", "HEAD"])
def audio(audio_id):
    path = os.path.join(AUDIO_DIR, f"live_{audio_id}.mp3")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        if request.method == "HEAD":
            return Response(status=200, mimetype="audio/mpeg")
        with open(path, "rb") as f:
            return Response(f.read(), mimetype="audio/mpeg")
    return ("No audio", 404)

if __name__ == "__main__":
    print("\n🎙  Live Stage Transcription System")
    print("─" * 42)
    print(f"  Platform    : {SYSTEM}")
    print(f"  pyaudio     : {'✓' if PYAUDIO_AVAILABLE else '✗ missing'}")
    print(f"  openai      : {'✓' if OPENAI_AVAILABLE else '✗ missing'}")
    print(f"  translator  : {'✓' if TRANSLATOR_AVAILABLE else '✗ missing'}")
    print(f"  gTTS        : {'✓' if GTTS_AVAILABLE else '✗ missing'}")
    print(f"  OpenAI key  : {'✓ set' if OPENAI_API_KEY else '✗ NOT SET'}")
    print(f"  ElevenLabs  : {'✓ set' if ELEVENLABS_API_KEY else '— not set (using gTTS)'}")
    print(f"  Language    : {LANGUAGES.get(state['target_lang'],{}).get('name','?')}")
    print(f"\n  Control panel : http://localhost:5050")
    print("─" * 42 + "\n")
    threading.Thread(target=playback_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)