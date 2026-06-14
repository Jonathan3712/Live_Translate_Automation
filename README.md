# Live Stage Transcription System

Real-time English speech transcription and translation for live events, churches, and conferences.

**Speaker talks in English → transcribed (Whisper) → translated (Google) → spoken in the selected language (gTTS) through local speakers.**

---

## Table of contents

1. [Features](#features)
2. [Quick start](#quick-start)
3. [First-time operator checklist](#first-time-operator-checklist)
4. [How it works](#how-it-works)
5. [Control panel guide](#control-panel-guide)
6. [Changing the output language](#changing-the-output-language)
7. [Glossary (Urdu term overrides)](#glossary-urdu-term-overrides)
8. [Audio chunking & tuning](#audio-chunking--tuning)
9. [Translation & TTS caching](#translation--tts-caching)
10. [Supported languages](#supported-languages)
11. [Configuration reference](#configuration-reference)
12. [API reference](#api-reference)
13. [Platform notes](#platform-notes)
14. [Development & testing](#development--testing)
15. [Troubleshooting](#troubleshooting)
16. [Cost](#cost)
17. [Project structure](#project-structure)

---

## Features

- **Live mic capture** with automatic voice-activity detection (VAD)
- **OpenAI Whisper** transcription (English)
- **Google Translate** via `deep-translator`
- **gTTS** text-to-speech in 11 languages
- **Local speaker playback** — Mac (`afplay`), Windows (`pygame`), Linux (`mpg123`)
- **Urdu glossary** — lock church/theology terms so Google Translate cannot override them
- **Translation & TTS caching** — repeated phrases play much faster
- **Web control panel** at `http://localhost:5050`
- **Real-time live feed** via Server-Sent Events (SSE)

---

## Quick start

### 1. Clone and enter the project

```bash
git clone https://github.com/Jonathan3712/Live_Translate_Automation.git
cd Live_Translate_Automation
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
```

### 3. Install system audio dependency (required for PyAudio)

**macOS:**
```bash
brew install portaudio
```

**Ubuntu / Debian:**
```bash
sudo apt-get update && sudo apt-get install -y portaudio19-dev
```

**Windows:** PyAudio wheels are usually included in `pip install`; if it fails, install [Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) and retry.

### 4. Install Python packages

```bash
pip install -r requirements.txt
```

**Windows only** — also install pygame for speaker playback:
```bash
pip install pygame
```

### 5. Configure API keys

```bash
cp .env.example .env
```

Edit `.env` and set your OpenAI key:

```
OPENAI_API_KEY=sk-your-key-here
```

Get a key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys).

### 6. Run the server

```bash
python app.py
```

Open the control panel: **http://localhost:5050**

On startup the terminal prints dependency status. All lines should show `OK` and `API key: SET` before a live session.

---

## First-time operator checklist

Use this before every event:

1. **Internet** — Whisper, Translate, and gTTS all need network access.
2. **Microphone** — connect the stage mic; in the control panel pick the correct **Input Device** (before pressing Start).
3. **Output language** — click a language pill (e.g. Urdu · اردو) before Start.
4. **Speaker volume** — turn up the machine's output volume; translated audio plays through **this computer's speakers**.
5. **Press Start** — wait for `VAD calibrated: noise=… threshold=…` in the terminal.
6. **Speak in English** — pause briefly between phrases (~1–2 seconds) so the system can segment speech.
7. **Watch the live feed** — English text and translation should appear within a few seconds per phrase.
8. **Press Stop** when finished.

---

## How it works

### Pipeline

```
Stage mic
    ↓
PyAudio capture + VAD segmentation (utterance chunks)
    ↓
OpenAI Whisper  →  English text
    ↓
Google Translate  →  Target language text
    ↓
gTTS  →  MP3 bytes
    ↓
Local speaker (afplay / pygame / mpg123)
```

The system does **not** transcribe word-by-word in real time. It waits for a short silence, sends the whole phrase to Whisper, then translates and plays audio. This is optimised for **sermon-style speech**, not rapid conversation.

### Background threads

When you press **Start**, four workers run in parallel:

| Thread | Role |
|--------|------|
| `recording_thread` | Reads mic, detects speech/silence, queues audio segments |
| `transcription_thread` | Sends segments to Whisper, filters hallucinations/duplicates |
| `translation_thread` | Translates English → selected language, generates TTS |
| `playback_worker` | Plays MP3 clips one at a time (no overlap) |

### Status indicators

| Status | Meaning |
|--------|---------|
| **Idle** | Not running |
| **Listening…** | Waiting for speech |
| **Transcribing…** | Sending audio to Whisper |
| **Translating…** | Running Translate + gTTS |

---

## Control panel guide

URL: **http://localhost:5050**

| Section | What it does |
|---------|--------------|
| **System Status** | Start / Stop the pipeline |
| **Input Device** | Select mic (must be chosen **before** Start; locked while running) |
| **Output Language** | Language pills — select which language is spoken through the speaker |
| **Live Feed** | Last 20 segments: timestamp, English, translation |

Links:
- **Glossary** — manage locked Urdu translation terms

---

## Changing the output language

### Option A — Control panel (recommended)

1. Open http://localhost:5050
2. Click a language pill under **Output Language**
3. Press **Start**

You can switch language between sessions. Language cannot be changed while the system is running.

### Option B — Default in code

Edit `SPEAKER_LANGUAGE` near the top of `app.py`:

```python
SPEAKER_LANGUAGE = "ur"   # Urdu (default)
# SPEAKER_LANGUAGE = "ne" # Nepali
# SPEAKER_LANGUAGE = "hi" # Hindi
```

Restart the server after changing. The control panel selection overrides this at runtime via `/api/speaker-lang`.

---

## Glossary (Urdu term overrides)

Google Translate may mistranslate church-specific English terms. The glossary forces exact Urdu replacements **before** translation is sent to Google.

### Using the glossary UI

1. Open http://localhost:5050/glossary
2. Add English → Urdu term pairs
3. Click 🔊 to preview pronunciation
4. Import/export JSON for bulk editing

### Glossary files

| File | Language |
|------|----------|
| `glossary_ur.json` | Urdu |
| `glossary_ne.json` | Nepali |
| `glossary_zh-CN.json` | Chinese |
| `glossary.json` | Legacy Urdu fallback |

Glossary changes take effect immediately and **invalidate** the translation cache for that language.

### Tips

- Add **longer phrases before shorter ones** — the system matches longest terms first
- Pre-load common liturgy terms before the service (they will also be **prewarmed** for TTS on Start)
- Use the Glossary page import for bulk uploads from a spreadsheet export

---

## Audio chunking & tuning

All segmentation settings are constants near the top of **`app.py`**. Change values, save, and **restart the server**.

### Where to edit

```python
# app.py — audio capture
SAMPLE_RATE = 16000
CHUNK_SIZE = 1024

# Utterance segmentation (~64 ms per chunk at 16 kHz / 1024 samples)
SILENCE_CHUNKS = 25
MIN_SPEECH_FRAMES = 5
MAX_SECONDS = 20
PRE_ROLL_CHUNKS = 5
AUDIO_QUEUE_MAX = 5
COOLDOWN_SECONDS = 1.5
VAD_CALIBRATION_CHUNKS = 32
VAD_MIN_THRESHOLD = 400
VAD_NOISE_MULTIPLIER = 2.5

# Default output language (overridable in UI)
SPEAKER_LANGUAGE = "ur"
```

### Chunk timing cheat sheet

Each chunk = `CHUNK_SIZE / SAMPLE_RATE` seconds (~64 ms with defaults).

| Chunks | Duration |
|--------|----------|
| 1 | ~64 ms |
| 5 | ~320 ms |
| 15 | ~1.0 s |
| 25 | ~1.6 s |
| 32 | ~2.0 s |

Formula: `milliseconds ≈ (chunks × CHUNK_SIZE / SAMPLE_RATE) × 1000`

### Setting reference

| Constant | Default | What it does |
|----------|---------|--------------|
| `SILENCE_CHUNKS` | `25` (~1.6 s) | Silence duration that ends an utterance. **Lower = faster.** Higher = waits for longer pauses. |
| `MIN_SPEECH_FRAMES` | `5` (~320 ms) | Minimum speech before sending. Filters coughs/clicks. Lower catches short words ("Amen"). |
| `MAX_SECONDS` | `20` | Hard cap per utterance; long monologues are cut here. |
| `PRE_ROLL_CHUNKS` | `5` (~320 ms) | Audio buffered before speech onset — prevents clipping the first syllable. |
| `COOLDOWN_SECONDS` | `1.5` | Gap after transcription/playback before a new utterance can start. Reduces speaker feedback. |
| `AUDIO_QUEUE_MAX` | `5` | Max queued clips for Whisper; oldest dropped if the speaker outruns the API. |
| `VAD_CALIBRATION_CHUNKS` | `32` (~2 s) | Room-noise sample at Start for auto threshold. |
| `VAD_MIN_THRESHOLD` | `400` | Minimum RMS threshold regardless of room noise. |
| `VAD_NOISE_MULTIPLIER` | `2.5` | Threshold = median noise × multiplier. Higher = less sensitive. |

### Runtime behaviour

1. Press **Start** → mic opens, ~2 s noise calibration runs
2. Terminal prints: `VAD calibrated: noise=120 threshold=400`
3. Speech above threshold starts an utterance (with pre-roll)
4. `SILENCE_CHUNKS` of silence ends the utterance (trailing silence is **not** included)
5. Clip → Whisper → Translate → gTTS → speaker
6. Cooldown prevents the mic from re-transcribing speaker output

### Recommended presets

**Stage / sermon (default):**
```python
SILENCE_CHUNKS = 25
MIN_SPEECH_FRAMES = 5
COOLDOWN_SECONDS = 1.5
```

**Faster turnaround:**
```python
SILENCE_CHUNKS = 15
MIN_SPEECH_FRAMES = 4
COOLDOWN_SECONDS = 1.0
```

**Noisy room:**
```python
VAD_MIN_THRESHOLD = 600
VAD_NOISE_MULTIPLIER = 3.0
MIN_SPEECH_FRAMES = 6
```

**Quiet / distant mic:**
```python
VAD_MIN_THRESHOLD = 300
VAD_NOISE_MULTIPLIER = 2.0
MIN_SPEECH_FRAMES = 4
```

### Whisper hallucination filters

Edit these lists in `app.py` if Whisper invents phrases in your environment:

- `NOISE_PHRASES` — substring matches (e.g. "thank you for watching")
- `HALLUCINATION_EXACT` — exact-match rejects (e.g. "thank you.")

The transcription thread also skips exact and near-duplicate (85% word overlap) segments.

---

## Translation & TTS caching

Repeated phrases skip slow network calls.

### What is cached

| Layer | Storage | Invalidated when |
|-------|---------|------------------|
| Translation | In-memory LRU (1000 entries) | Glossary edit (Urdu); LRU eviction |
| TTS audio | Memory LRU (500) + disk `cache/tts/` | Manual delete of `cache/` folder |
| Glossary | In-memory | Glossary save via UI/API |
| API clients | In-memory | Server restart |

Whisper is **never** cached — each live utterance is unique.

### Cache constants (`app.py`)

```python
TRANSLATION_CACHE_MAX = 1000
TTS_MEMORY_CACHE_MAX = 500
```

### Prewarm on Start

A background thread pre-caches translation + TTS for all **Urdu glossary** entries. After the first run, liturgy terms play almost instantly.

### Monitoring

`GET /status` returns:
```json
{
  "running": true,
  "status": "listening",
  "speaker_lang": "ur",
  "cache": {
    "translation_entries": 42,
    "tts_memory_entries": 38
  }
}
```

Terminal logs: `Translation cache hit`, `TTS cache hit (memory)`, `TTS cache hit (disk)`.

To clear disk cache: `rm -rf cache/`

---

## Supported languages

| Code | Language | gTTS code |
|------|----------|-----------|
| `ur` | Urdu | `ur` |
| `ne` | Nepali | `ne` (slow speech) |
| `zh-CN` | Chinese | `zh-CN` |
| `hi` | Hindi | `hi` |
| `ar` | Arabic | `ar` |
| `es` | Spanish | `es` |
| `fr` | French | `fr` |
| `tr` | Turkish | `tr` |
| `pt` | Portuguese | `pt` |
| `sw` | Swahili | `sw` |
| `pa` | Punjabi | `pa` |

To add a language, add an entry to the `LANGUAGES` dict in `app.py` (name, gTTS code, label).

---

## Configuration reference

| Item | Location | Notes |
|------|----------|-------|
| OpenAI API key | `.env` → `OPENAI_API_KEY` | Required |
| Default language | `app.py` → `SPEAKER_LANGUAGE` | Overridable in UI |
| Segmentation tuning | `app.py` constants | See [Audio chunking](#audio-chunking--tuning) |
| Cache sizes | `app.py` → `TRANSLATION_CACHE_MAX`, `TTS_MEMORY_CACHE_MAX` | |
| Input device | Control panel | Stored in server state |
| Server port | `app.py` bottom → `port=5050` | Default 5050 |
| Bind address | `host="0.0.0.0"` | Accessible on LAN |

---

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Control panel UI |
| `GET` | `/glossary` | Glossary manager UI |
| `GET` | `/stream` | SSE live events |
| `POST` | `/start` | Start pipeline |
| `POST` | `/stop` | Stop pipeline |
| `GET` | `/status` | Running state + cache stats |
| `GET` | `/api/languages` | All supported languages |
| `POST` | `/api/speaker-lang` | Set output language `{"lang": "ur"}` |
| `GET` | `/api/devices` | List input devices |
| `POST` | `/api/devices` | Set input device `{"index": 0}` |
| `GET` | `/api/glossary?lang=ur` | Get glossary JSON |
| `POST` | `/api/glossary?lang=ur` | Add term `{"english": "...", "urdu": "..."}` |
| `DELETE` | `/api/glossary/<term>?lang=ur` | Remove term |
| `POST` | `/api/glossary/import?lang=ur` | Bulk import JSON object |
| `POST` | `/api/pronounce` | TTS preview `{"text": "...", "lang": "ur"}` |

### SSE event types

| Type | Payload | When |
|------|---------|------|
| `init` | status, lang, langs | Client connects |
| `status` | `listening`, `transcribing`, `translating` | Pipeline state change |
| `transcript` | english, translated, lang, ts | New segment |
| `lang_changed` | lang, name | Language switched |
| `error` | message | API failure |
| `ping` | — | Keep-alive every 30 s |

---

## Platform notes

| Platform | Speaker playback | Notes |
|----------|------------------|-------|
| **macOS** | `afplay` (built-in) | No extra install |
| **Windows** | `pygame` | `pip install pygame` |
| **Linux** | `mpg123` | `sudo apt-get install mpg123` |

The server binds to `0.0.0.0:5050`, so other devices on the same network can open the control panel at `http://<your-ip>:5050`.

---

## Development & testing

### Run locally

```bash
source venv/bin/activate
python app.py
```

### Lint (matches CI)

```bash
./scripts/run_pylint.sh          # check
./scripts/run_pylint.sh --fix    # auto-fix style, then check
```

### Tests

```bash
pip install pytest
pytest
```

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | Whisper transcription |
| `ELEVENLABS_API_KEY` | No | Reserved for future TTS |

---

## Troubleshooting

### Setup

| Problem | Solution |
|---------|----------|
| `pyaudio not installed` | `pip install pyaudio`; install `portaudio` system library |
| `OPENAI_API_KEY missing` | Create `.env` from `.env.example` |
| PyAudio install fails on Mac | `brew install portaudio` then retry pip |
| No sound on Windows | `pip install pygame` |
| No sound on Linux | `sudo apt-get install mpg123` |

### Live session

| Problem | Solution |
|---------|----------|
| Nothing transcribed | Check mic device; speak louder; lower `VAD_NOISE_MULTIPLIER` |
| Slow response after speaking | Lower `SILENCE_CHUNKS` |
| One sentence split in two | Raise `SILENCE_CHUNKS` |
| First word clipped | Raise `PRE_ROLL_CHUNKS` |
| Coughs transcribed | Raise `MIN_SPEECH_FRAMES` |
| Short words ignored | Lower `MIN_SPEECH_FRAMES` |
| Speaker output re-transcribed | Raise `COOLDOWN_SECONDS` |
| Old phrases play late | Lower `AUDIO_QUEUE_MAX` |
| `PaMacCore` / audio unit errors | Select a different input device; close other apps using the mic |
| Repeated phrase still slow first time | Normal — second occurrence uses cache |
| Urdu term wrong | Add/fix entry in Glossary |

### Chunking tuning

See the full symptom table in [Audio chunking & tuning](#audio-chunking--tuning).

---

## Cost

| Service | Typical cost |
|---------|--------------|
| OpenAI Whisper | ~$0.006 / minute of audio (~$0.43 per 2 hr event) |
| Google Translate | Free (via `deep-translator`) |
| gTTS | Free |

Billing is on your OpenAI account. Cache hits reduce Translate/gTTS network time but **do not** reduce Whisper cost.

---

## Project structure

```
Live_Translate_Automation/
├── app.py                  # Main server — pipeline, API, tuning constants
├── requirements.txt        # Python dependencies
├── .env.example            # API key template
├── .env                    # Your keys (never commit)
├── cache/                  # TTS disk cache (auto-created, gitignored)
├── glossary_ur.json        # Urdu glossary (optional, create via UI)
├── glossary_ne.json        # Nepali glossary (optional)
├── scripts/
│   └── run_pylint.sh       # Local lint script
├── tests/
│   └── test_smoke.py       # Import smoke test
├── templates/
│   ├── index.html          # Control panel
│   └── glossary.html       # Glossary manager
└── .github/workflows/      # CI (pytest + pylint)
```

---

## Contributing

1. Create a feature branch from `main`
2. Make changes; run `./scripts/run_pylint.sh` and `pytest`
3. Open a pull request

For platform-specific audio playback changes, test on the target OS before merging.
