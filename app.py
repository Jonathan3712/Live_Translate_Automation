"""
Live Stage Transcription System
Mic → Whisper (English) → Big Screen + Claude (Urdu) → ElevenLabs/gTTS (Spoken)

Architecture: continuous recording with parallel processing
- Thread 1: records audio non-stop, pushes chunks to audio_queue
- Thread 2: pulls chunks, transcribes + translates, pushes results to SSE
This means NO audio is ever dropped while processing is happening.
"""

import os
import json
import time
import queue
import struct
import threading
import tempfile
import wave
from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
from flask import Flask, render_template, Response, jsonify, request
from flask_cors import CORS

# ── Optional imports (graceful fallback) ────────────────────────────────────
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("⚠ pyaudio not installed. Run: pip install pyaudio")

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("⚠ openai not installed. Run: pip install openai")

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False
    print("⚠ deep_translator not installed. Run: pip install deep-translator")

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False
    print("⚠ gTTS not installed. Run: pip install gTTS")

# ── Config ───────────────────────────────────────────────────────────────────
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# Audio settings
SAMPLE_RATE    = 16000
CHUNK_SIZE     = 1024
CHANNELS       = 1
RECORD_SECONDS = 4   # each audio chunk length — shorter = faster updates

# Silence / noise filter
NOISE_PHRASES = [
    "thank you for watching", "thank you for listening", "thanks for watching",
    "thanks for listening", "please subscribe", "don't forget to subscribe",
    "like and subscribe", "subtitles by", "[music]", "[applause]",
    # Whisper leaking its own prompt back
    "do not add filler", "don't add filler", "do not repeat",
    "transcribe only", "filler words",
]

# Whisper hallucination — only block if ENTIRE output is one of these
HALLUCINATION_EXACT = {
    "thank you. thank you.", "thanks. thanks.",
    "thank you, thank you.", "thank you! thank you!",
    "goodbye.", "goodbye", "bye.", "bye",
}

app = Flask(__name__)
CORS(app)

# ── Shared state ─────────────────────────────────────────────────────────────
state = {
    "running": False,
    "muted": False,
    "cooldown_until": 0,   # timestamp — ignore audio until this time passes
    "last_english": "",
    "english_text": "",
    "urdu_text": "",
    "history": [],
    "status": "idle",
    "error": None,
}
sse_queue    = queue.Queue()  # kept for legacy — now unused
audio_queue  = queue.Queue()
playback_queue = queue.Queue()

# ── Clients ───────────────────────────────────────────────────────────────────
def get_openai():
    if not OPENAI_AVAILABLE:
        raise RuntimeError("openai package not installed")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    return OpenAI(api_key=OPENAI_API_KEY)

# ── SSE push — defined after sse_clients registry below ──────────────────────

# ── Playback worker — plays audio files one by one via afplay ─────────────────
def playback_worker():
    """
    Single dedicated thread for audio playback.
    Plays files sequentially — no overlapping.
    Mutes mic during playback + 3s cooldown after to stop Whisper hallucinations.
    """
    import subprocess
    while True:
        try:
            audio_path = playback_queue.get(timeout=2)
        except queue.Empty:
            continue
        if audio_path is None:
            break
        try:
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                print(f"🔈 Playing: {os.path.basename(audio_path)}")
                state["muted"] = True
                # Extend cooldown to cover full playback duration + buffer
                file_size = os.path.getsize(audio_path)
                estimated_secs = file_size / 16000
                state["cooldown_until"] = time.time() + estimated_secs + 4.0
                subprocess.run(["afplay", audio_path], check=True)
                # Extra post-playback cooldown — stops Whisper picking up echo
                time.sleep(3.0)
                state["cooldown_until"] = time.time() + 1.0
                state["muted"] = False
                print(f"✓ Done: {os.path.basename(audio_path)}")
        except Exception as e:
            state["muted"] = False
            print(f"✗ Playback error: {e}")

# ── Voice Activity Detection (VAD) helpers ────────────────────────────────────
def is_speech(frame: bytes, threshold: int = 500) -> bool:
    """
    Simple energy-based VAD.
    Unpacks 16-bit PCM samples and checks if RMS energy is above threshold.
    threshold=500 works well for a quiet room with a Mac mic.
    Lower it (eg 300) if speech is soft. Raise it (eg 800) if noisy.
    """
    samples = struct.unpack(f"{len(frame)//2}h", frame)
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    return rms > threshold

# ── Thread 1: Smart VAD-based recorder ────────────────────────────────────────
def recording_thread():
    """
    Instead of cutting every N seconds blindly, this waits for:
      - Speech to START  (voice detected)
      - Speech to END    (silence for SILENCE_CHUNKS consecutive frames)
    Then sends the whole utterance as one clean chunk.

    Result: Whisper always gets complete sentences → much better accuracy.

    Safety cap: if someone talks for >MAX_SECONDS without pausing,
    we flush anyway so the display doesn't lag too far behind.
    """
    SILENCE_CHUNKS = 40   # ~1s of silence before cutting (was 25 — too aggressive)
    MAX_SECONDS    = 15   # allow longer utterances
    THRESHOLD      = 400
    MIN_SPEECH_FRAMES = 8  # must hear at least ~0.2s of speech before recording

    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SIZE,
    )
    print("🎙 VAD recording thread started")
    try:
        while state["running"]:
            frames          = []
            silence_count   = 0
            speaking        = False
            max_frames      = int(SAMPLE_RATE / CHUNK_SIZE * MAX_SECONDS)

            # Wait for speech to begin — skip if in cooldown
            while state["running"]:
                frame = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                if time.time() < state["cooldown_until"]:
                    continue   # still in cooldown, drain mic silently
                if is_speech(frame, THRESHOLD):
                    speaking = True
                    frames.append(frame)
                    break

            if not speaking:
                continue

            # Collect frames until silence or max length
            while state["running"] and len(frames) < max_frames:
                frame = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                frames.append(frame)
                if is_speech(frame, THRESHOLD):
                    silence_count = 0        # still talking, reset counter
                else:
                    silence_count += 1
                    if silence_count >= SILENCE_CHUNKS:
                        break                # natural pause → end of sentence

            if frames and len(frames) >= MIN_SPEECH_FRAMES:
                audio_queue.put(b"".join(frames))
            else:
                print(f"⏭ Too short ({len(frames)} frames), skipping")

    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
        print("🎙 Recording thread stopped")

def pcm_to_wav(pcm: bytes) -> bytes:
    """Wrap raw PCM in a proper WAV container (required by Whisper API)."""
    buf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(buf.name, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)          # 16-bit = 2 bytes
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    path = buf.name
    with open(path, "rb") as f:
        data = f.read()
    os.unlink(path)
    return data

# ── Transcription (Whisper) ────────────────────────────────────────────────────
def transcribe(wav_bytes: bytes) -> str:
    client = get_openai()
    # Whisper always translates to English when task="translate"
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
                # This prompt suppresses Whisper's hallucination behavior
                prompt="Transcribe only what is actually spoken. Do not add filler words, do not repeat previous sentences, do not add thank you or goodbye.",
            )
        return result.strip() if isinstance(result, str) else result.text.strip()
    finally:
        os.unlink(tmp.name)

# ── Glossary system ───────────────────────────────────────────────────────────
GLOSSARY_FILE = os.path.join(os.path.dirname(__file__), "glossary.json")

def load_glossary() -> dict:
    """Load glossary from disk. Returns {english: urdu} dict."""
    if os.path.exists(GLOSSARY_FILE):
        with open(GLOSSARY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # Default church/scripture terms to get started
    return {
        "Jesus":        "یسوع",
        "Jesus Christ": "یسوع مسیح",
        "Holy Spirit":  "روح القدس",
        "God":          "خدا",
        "Lord":         "خداوند",
        "Grace":        "فضل",
        "Amen":         "آمین",
        "Gospel":       "انجیل",
        "Hallelujah":   "ہللویاہ",
        "Scripture":    "کلام مقدس",
        "Righteousness":"راستبازی",
        "Salvation":    "نجات",
        "Kingdom":      "بادشاہی",
        "Heaven":       "آسمان",
        "Baptism":      "بپتسمہ",
        "Church":       "کلیسیا",
        "Prayer":       "دعا",
        "Worship":      "عبادت",
        "Bible":        "بائبل",
        "Faith":        "ایمان",
    }

def save_glossary(glossary: dict):
    """Save glossary to disk."""
    with open(GLOSSARY_FILE, "w", encoding="utf-8") as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)

def apply_glossary(text: str, glossary: dict) -> str:
    """
    Replace glossary terms in text.
    Case-insensitive match, preserves surrounding words.
    Longer phrases matched first to avoid partial replacements.
    """
    import re
    # Sort by length descending — match "Jesus Christ" before "Jesus"
    for english, urdu in sorted(glossary.items(), key=lambda x: -len(x[0])):
        pattern = re.compile(re.escape(english), re.IGNORECASE)
        text = pattern.sub(urdu, text)
    return text

# ── Translation with glossary lock ───────────────────────────────────────────
def translate_to_urdu(english: str) -> str:
    """
    Translation pipeline:
    1. Apply glossary to English BEFORE translate (protect key terms)
    2. Google Translate the full text
    3. Apply glossary AFTER translate (fix any overrides)
    """
    glossary = load_glossary()

    # Step 1 — protect glossary terms by replacing with placeholders
    import re
    placeholders = {}
    protected = english
    for i, (eng, urd) in enumerate(sorted(glossary.items(), key=lambda x: -len(x[0]))):
        pattern = re.compile(re.escape(eng), re.IGNORECASE)
        if pattern.search(protected):
            placeholder = f"__TERM{i}__"
            placeholders[placeholder] = urd
            protected = pattern.sub(placeholder, protected)

    # Step 2 — translate (placeholders pass through untouched)
    translated = GoogleTranslator(source='en', target='ur').translate(protected)

    # Step 3 — restore glossary terms (guaranteed correct Urdu)
    for placeholder, urdu in placeholders.items():
        translated = translated.replace(placeholder, urdu)

    return translated.strip()

# ── TTS (gTTS fallback, ElevenLabs if key present) ────────────────────────────
def speak_urdu(urdu_text: str, audio_id: str) -> str:
    """Generate audio file with unique ID, return audio_id on success."""
    out_path = f"/tmp/urdu_{audio_id}.mp3"
    print(f"🔊 TTS generating: {audio_id} → '{urdu_text[:40]}...'")

    if ELEVENLABS_API_KEY:
        import requests
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        voice_id = "pNInz6obpgDQGcFmaJgB"
        payload  = {
            "text": urdu_text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
        }
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers=headers, json=payload
        )
        if r.status_code == 200:
            with open(out_path, "wb") as f:
                f.write(r.content)
            print(f"✓ ElevenLabs audio ready: {audio_id} ({os.path.getsize(out_path)} bytes)")
            return audio_id
        else:
            print(f"⚠ ElevenLabs failed ({r.status_code}), falling back to gTTS")

    if GTTS_AVAILABLE:
        tts = gTTS(text=urdu_text, lang="ur")
        tts.save(out_path)
        print(f"✓ gTTS audio ready: {audio_id} ({os.path.getsize(out_path)} bytes)")
        return audio_id

    print(f"✗ No TTS available for {audio_id}")
    return ""


def tts_thread(urdu: str, audio_id: str):
    """
    Generates TTS audio file then puts it in the playback queue.
    Never blocks the processing pipeline.
    """
    try:
        speak_urdu(urdu, audio_id)
        audio_path = f"/tmp/urdu_{audio_id}.mp3"
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            playback_queue.put(audio_path)
            print(f"📥 Queued for playback: {audio_id}")
        else:
            print(f"✗ Audio file missing: {audio_path}")
    except Exception as e:
        print(f"✗ TTS error for {audio_id}: {e}")

# ── Thread 2: Processing worker ───────────────────────────────────────────────
def processing_thread():
    """
    Thread 2: Transcribe + Translate only.
    Immediately pushes text to browser then hands off to TTS thread.
    Never waits for audio — text appears on screen instantly.
    """
    print("⚙ Processing thread started")
    while state["running"] or not audio_queue.empty():
        try:
            pcm = audio_queue.get(timeout=2)
        except queue.Empty:
            continue

        try:
            # Transcribe
            state["status"] = "transcribing"
            push_event("status", {"status": "transcribing"})
            wav = pcm_to_wav(pcm)
            english = transcribe(wav)

            # Filter silence / noise
            if not english or len(english) < 2:
                state["status"] = "listening"
                push_event("status", {"status": "listening"})
                continue

            # Filter known Whisper hallucination phrases (exact short fillers)
            if english.strip().lower().rstrip('.!?,') in HALLUCINATION_EXACT:
                print(f"⏭ Hallucination filtered: '{english}'")
                state["status"] = "listening"
                push_event("status", {"status": "listening"})
                continue

            # Filter known noise/spam phrases
            if any(p in english.lower() for p in NOISE_PHRASES):
                print(f"⏭ Noise filtered: '{english[:50]}'")
                state["status"] = "listening"
                push_event("status", {"status": "listening"})
                continue

            # Filter exact duplicates only — Whisper repeating identical text
            last = state["last_english"].strip().lower()
            curr = english.strip().lower()
            if curr == last:
                print(f"⏭ Exact duplicate skipped: '{english[:50]}'")
                state["status"] = "listening"
                push_event("status", {"status": "listening"})
                continue

            state["last_english"] = english
            # Set 2s cooldown so mic ignores residual noise after this utterance
            state["cooldown_until"] = time.time() + 2.0

            state["english_text"] = english

            # Translate
            state["status"] = "translating"
            push_event("status", {"status": "translating"})
            urdu = translate_to_urdu(english)
            state["urdu_text"] = urdu

            # Generate unique audio ID for this segment
            audio_id = str(int(time.time() * 1000))

            # Push text to browser IMMEDIATELY — don't wait for TTS
            entry = {
                "english":  english,
                "urdu":     urdu,
                "ts":       time.strftime("%H:%M:%S"),
                "audio":    True,
                "audio_id": audio_id,
            }
            print(f"📝 Transcript: '{english[:50]}' → audio_id: {audio_id}")
            state["history"].insert(0, entry)
            state["history"] = state["history"][:30]
            push_event("transcript", entry)

            # Hand off TTS to its own thread — pipeline continues instantly
            threading.Thread(
                target=tts_thread,
                args=(urdu, audio_id),
                daemon=True
            ).start()

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


# ── Audio playback queue ──────────────────────────────────────────────────────
# TTS files are generated in parallel threads (fast)
# Playback happens sequentially in ONE dedicated thread (no overlapping)
playback_queue = queue.Queue()

def playback_worker():
    """
    Single dedicated thread that plays audio files one by one.
    Runs forever while app is running.
    afplay blocks until done — that's intentional here, it's the playback thread.
    Mic muted only during actual playback + short cooldown.
    """
    import subprocess
    while True:
        try:
            audio_path = playback_queue.get(timeout=2)
        except queue.Empty:
            continue
        if audio_path is None:
            break   # shutdown signal
        try:
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                print(f"🔈 Playing: {os.path.basename(audio_path)}")
                state["muted"] = True
                # Estimate audio duration and extend cooldown to cover it
                file_size = os.path.getsize(audio_path)
                estimated_seconds = file_size / 16000  # rough mp3 estimate
                state["cooldown_until"] = time.time() + estimated_seconds + 2.0
                subprocess.run(["afplay", audio_path], check=True)
                time.sleep(0.8)
                state["cooldown_until"] = time.time() + 1.5  # post-playback cooldown
                state["muted"] = False
                print(f"✓ Done: {os.path.basename(audio_path)}")
        except Exception as e:
            state["muted"] = False
            print(f"✗ Playback error: {e}")


def tts_thread(urdu: str, audio_id: str):
    """
    Generates TTS audio file, then puts it in the playback queue.
    Generation runs in parallel — never blocks transcription.
    Playback is handled by the dedicated playback_worker thread.
    """
    try:
        speak_urdu(urdu, audio_id)
        audio_path = f"/tmp/urdu_{audio_id}.mp3"
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            playback_queue.put(audio_path)
            print(f"📥 Queued for playback: {audio_id}")
        else:
            print(f"✗ Audio file missing: {audio_path}")
    except Exception as e:
        print(f"✗ TTS error for {audio_id}: {e}")

# ── Flask routes ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/glossary")
def glossary_page():
    return render_template("glossary.html")

@app.route("/api/glossary", methods=["GET"])
def get_glossary():
    return jsonify(load_glossary())

@app.route("/api/glossary", methods=["POST"])
def add_term():
    data = request.get_json()
    english = data.get("english", "").strip()
    urdu    = data.get("urdu", "").strip()
    if not english or not urdu:
        return jsonify({"ok": False, "msg": "Both English and Urdu required"})
    glossary = load_glossary()
    glossary[english] = urdu
    save_glossary(glossary)
    print(f"📖 Glossary added: '{english}' → '{urdu}'")
    return jsonify({"ok": True})

@app.route("/api/glossary/<path:term>", methods=["DELETE"])
def delete_term(term):
    glossary = load_glossary()
    if term in glossary:
        del glossary[term]
        save_glossary(glossary)
        print(f"📖 Glossary removed: '{term}'")
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "Term not found"})

@app.route("/api/pronounce", methods=["POST"])
def pronounce():
    """Generate and serve Urdu audio for a glossary term."""
    data = request.get_json()
    urdu = data.get("urdu", "").strip()
    if not urdu:
        return ("No text", 400)
    try:
        from gtts import gTTS
        import io
        tts = gTTS(text=urdu, lang="ur")
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return Response(buf.read(), mimetype="audio/mpeg")
    except Exception as e:
        return (str(e), 500)
def import_glossary():
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"ok": False, "msg": "Invalid format — expected a JSON object"})
    # Merge with existing — new terms override old ones
    glossary = load_glossary()
    glossary.update(data)
    save_glossary(glossary)
    print(f"📖 Glossary imported: {len(data)} terms added/updated")
    return jsonify({"ok": True, "count": len(data), "total": len(glossary)})
def update_term(term):
    data = request.get_json()
    urdu = data.get("urdu", "").strip()
    if not urdu:
        return jsonify({"ok": False, "msg": "Urdu translation required"})
    glossary = load_glossary()
    glossary[term] = urdu
    save_glossary(glossary)
    print(f"📖 Glossary updated: '{term}' → '{urdu}'")
    return jsonify({"ok": True})

# ── Per-client SSE queue registry ─────────────────────────────────────────────
import uuid
sse_clients = {}   # {client_id: queue.Queue()}
sse_lock    = threading.Lock()

def push_event(event_type: str, data: dict):
    """Push event to ALL connected SSE clients."""
    payload = f"data: {json.dumps({'type': event_type, **data})}\n\n"
    with sse_lock:
        for q in sse_clients.values():
            q.put(payload)

@app.route("/stream")
def stream():
    """SSE endpoint — each browser tab gets its own queue."""
    client_id = str(uuid.uuid4())
    q = queue.Queue()
    with sse_lock:
        sse_clients[client_id] = q

    def generate():
        # Send full current state immediately on connect
        yield f"data: {json.dumps({'type':'init','history':state['history'],'status':state['status']})}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
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
        return jsonify({"ok": False, "msg": "OPENAI_API_KEY missing"})
    state["running"] = True
    state["error"] = None
    state["last_english"] = ""
    while not audio_queue.empty():
        audio_queue.get_nowait()
    threading.Thread(target=recording_thread,  daemon=True).start()
    threading.Thread(target=processing_thread, daemon=True).start()
    # playback_worker is started once at app boot — do NOT start it here
    push_event("status", {"status": "listening"})
    return jsonify({"ok": True})

@app.route("/stop", methods=["POST"])
def stop():
    state["running"] = False
    state["muted"] = False
    # Clear any queued audio from this session
    while not playback_queue.empty():
        try: playback_queue.get_nowait()
        except: break
    return jsonify({"ok": True})

@app.route("/audio/<audio_id>", methods=["GET", "HEAD"])
def audio(audio_id):
    """Serve a specific Urdu TTS audio file by its ID."""
    path = f"/tmp/urdu_{audio_id}.mp3"
    if os.path.exists(path) and os.path.getsize(path) > 0:
        if request.method == "HEAD":
            return Response(status=200, mimetype="audio/mpeg")
        with open(path, "rb") as f:
            return Response(f.read(), mimetype="audio/mpeg")
    return ("No audio", 404)

@app.route("/status")
def status():
    return jsonify({
        "running": state["running"],
        "status": state["status"],
        "error": state["error"],
        "history_count": len(state["history"]),
    })

if __name__ == "__main__":
    print("\n🎙  Live Stage Transcription System")
    print("─" * 40)
    print(f"  pyaudio     : {'✓' if PYAUDIO_AVAILABLE else '✗ missing'}")
    print(f"  openai      : {'✓' if OPENAI_AVAILABLE else '✗ missing'}")
    print(f"  translator  : {'✓' if TRANSLATOR_AVAILABLE else '✗ missing'}")
    print(f"  gTTS        : {'✓' if GTTS_AVAILABLE else '✗ missing'}")
    print(f"  OpenAI key  : {'✓ set' if OPENAI_API_KEY else '✗ NOT SET'}")
    print(f"  ElevenLabs  : {'✓ set' if ELEVENLABS_API_KEY else '— not set (using gTTS)'}")
    print("\n  Control panel : http://localhost:5050")
    print("  Big screen    : http://localhost:5050/display")
    print("─" * 40 + "\n")

    # Start ONE persistent playback worker — never restarted
    threading.Thread(target=playback_worker, daemon=True).start()

    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)