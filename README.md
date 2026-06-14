# Live Stage Transcription System

Real-time speech transcription and translation for live events, churches, and conferences.

**Speaker talks in English -> transcribed -> translated -> spoken in target language**

---

## Overview

This repository contains the Live Stage Transcription System with platform-specific branches:

| Branch | Platform | Audio Method |
|---|---|---|
| `main` | Reference only | - |
| `mac` | macOS | afplay (built-in) |
| `windows` | Windows 10/11 | pygame in-memory |

---

## Quick Start

**Clone for Mac:**
```bash
git clone -b mac https://github.com/Jonathan3712/live-transcribe.git
```

**Clone for Windows:**
```bash
git clone -b windows https://github.com/Jonathan3712/live-transcribe.git
```

---

## How It Works

```
Stage mic -> Mixer -> USB -> Mac/PC
                              |
                    OpenAI Whisper
                    (speech to English)
                              |
                    Google Translate
                    (English -> selected language)
                              |
                    gTTS
                    (text -> spoken audio)
                              |
                    Local speaker output
```

The system does **not** stream audio word-by-word. It records the mic in short **utterances** (phrases), sends each clip to Whisper when the speaker pauses, then translates and plays the result. Tuning how those utterances are cut is the main way to control speed vs accuracy.

---

## Audio Chunking & Tuning

All audio segmentation settings live near the top of **`app.py`** (around lines 69–82). Change the values there, save, and **restart the server** (`python app.py`).

### Where to edit

```python
# app.py

SAMPLE_RATE = 16000
CHUNK_SIZE = 1024

# Utterance segmentation tuning (~64 ms per chunk at 16 kHz / 1024 samples)
SILENCE_CHUNKS = 25
MIN_SPEECH_FRAMES = 5
MAX_SECONDS = 20
PRE_ROLL_CHUNKS = 5
AUDIO_QUEUE_MAX = 5
COOLDOWN_SECONDS = 1.5
VAD_CALIBRATION_CHUNKS = 32
VAD_MIN_THRESHOLD = 400
VAD_NOISE_MULTIPLIER = 2.5

# Output language for translated speech
SPEAKER_LANGUAGE = "ur"
```

### Chunk timing cheat sheet

Each chunk is `CHUNK_SIZE / SAMPLE_RATE` seconds. With the defaults (1024 samples @ 16 kHz):

| Unit | Duration |
|------|----------|
| 1 chunk | ~64 ms |
| 5 chunks | ~320 ms |
| 25 chunks | ~1.6 s |
| 32 chunks | ~2.0 s |

To convert any setting to milliseconds:

```
milliseconds ≈ (setting_value × CHUNK_SIZE / SAMPLE_RATE) × 1000
```

### Setting reference

| Constant | Default | What it does |
|----------|---------|--------------|
| `SILENCE_CHUNKS` | `25` (~1.6 s) | How long the speaker must be silent before an utterance is sent to Whisper. **Lower = faster response.** Higher = waits for longer pauses (better for slow, deliberate speech). |
| `MIN_SPEECH_FRAMES` | `5` (~320 ms) | Minimum speech length before a clip is worth sending. Filters coughs and mic bumps. **Lower** catches short words ("Yes", "Amen"). **Higher** ignores more noise. |
| `MAX_SECONDS` | `20` | Hard limit on utterance length. Very long sentences are cut and sent without waiting for silence. |
| `PRE_ROLL_CHUNKS` | `5` (~320 ms) | Audio kept in a rolling buffer **before** speech is detected, then prepended to the clip so the first syllable is not clipped. |
| `COOLDOWN_SECONDS` | `1.5` | Pause after a successful transcription (and after TTS playback) before a **new** utterance can start. Reduces the mic picking up translated audio from the speakers. |
| `AUDIO_QUEUE_MAX` | `5` | Max queued utterances waiting for Whisper. If the speaker talks faster than the API can process, the **oldest** clip is dropped. |
| `VAD_CALIBRATION_CHUNKS` | `32` (~2 s) | How much room noise to sample when you press **Start**, used to set the speech-detection threshold automatically. |
| `VAD_MIN_THRESHOLD` | `400` | Floor for the speech threshold. Raise in very noisy rooms if the mic false-triggers. Lower only if quiet speech is missed and calibration is not enough. |
| `VAD_NOISE_MULTIPLIER` | `2.5` | Threshold = median room noise × this value. **Higher** = less sensitive (fewer false starts). **Lower** = more sensitive. |
| `SPEAKER_LANGUAGE` | `"ur"` | Language code for translation and TTS playback (`"ur"`, `"ne"`, `"hi"`, etc.). Must match a key in the `LANGUAGES` dict in `app.py`. |

### What happens at runtime

1. Press **Start** on the control panel.
2. The app records ~2 seconds of room noise and prints something like:
   ```
   VAD calibrated: noise=120 threshold=400
   ```
3. When RMS level exceeds the threshold, an utterance starts (with pre-roll).
4. When silence lasts for `SILENCE_CHUNKS`, the clip is trimmed and queued for Whisper.
5. After transcription, translation, and speaker playback, `COOLDOWN_SECONDS` applies before the next utterance can begin.

### Recommended presets

**Stage / sermon (default)** — complete phrases, natural pauses:

```python
SILENCE_CHUNKS = 25
MIN_SPEECH_FRAMES = 5
COOLDOWN_SECONDS = 1.5
```

**Faster turnaround** — shorter pauses, snappier (may split mid-thought if the speaker pauses briefly):

```python
SILENCE_CHUNKS = 15      # ~1.0 s
MIN_SPEECH_FRAMES = 4
COOLDOWN_SECONDS = 1.0
```

**Noisy room** — reduce false triggers from crowd/HVAC:

```python
VAD_MIN_THRESHOLD = 600
VAD_NOISE_MULTIPLIER = 3.0
MIN_SPEECH_FRAMES = 6
```

**Quiet mic or distant speaker** — catch softer speech:

```python
VAD_MIN_THRESHOLD = 300
VAD_NOISE_MULTIPLIER = 2.0
MIN_SPEECH_FRAMES = 4
```

### Troubleshooting

| Symptom | Try adjusting |
|---------|----------------|
| Translation feels slow / long delay after speaking | Lower `SILENCE_CHUNKS` |
| One sentence split into two translations | Raise `SILENCE_CHUNKS` |
| First word of each phrase cut off | Raise `PRE_ROLL_CHUNKS` |
| Coughs or bumps get transcribed | Raise `MIN_SPEECH_FRAMES` |
| Short words ("Yes", "No") ignored | Lower `MIN_SPEECH_FRAMES` |
| Mic triggers on room noise | Raise `VAD_NOISE_MULTIPLIER` or `VAD_MIN_THRESHOLD` |
| Soft speech not detected | Lower `VAD_NOISE_MULTIPLIER` or `VAD_MIN_THRESHOLD` |
| Translated audio re-transcribed (feedback loop) | Raise `COOLDOWN_SECONDS` |
| Old phrases play long after the speaker moved on | Lower `AUDIO_QUEUE_MAX` |
| Very long monologue gets cut mid-sentence | Raise `MAX_SECONDS` |

### Other `app.py` settings

- **Input device** — chosen in the control panel UI (stored in server state, not a constant).
- **Whisper hallucination filters** — `NOISE_PHRASES` and `HALLUCINATION_EXACT` lists in `app.py`; add phrases Whisper invents in your environment.
- **Glossary** — per-language JSON files and the Glossary page; used for Urdu term overrides during translation.

---

## Supported Languages

Urdu, Chinese, Nepali, Hindi, Arabic, Spanish, French, Turkish, Portuguese, Swahili, Punjabi

---

## Cost

| Service | Cost |
|---|---|
| OpenAI Whisper | ~$0.43 per 2hr event |
| Google Translate | Free |
| gTTS | Free |

---

## Requirements

- Python 3.11
- OpenAI API key (platform.openai.com/api-keys)
- Internet connection

---

## Contributing

- Work on `mac` branch for Mac-specific changes
- Work on `windows` branch for Windows-specific changes
- Merge to `main` only for shared changes (glossary, templates, README)

---

## Project Structure

```
live-transcribe/
├── app.py                  <- Main server
├── requirements.txt        <- Python dependencies
├── .env.example            <- API key template
├── .env                    <- Your keys (never commit)
├── glossary_ur.json        <- Urdu glossary
├── glossary_zh-CN.json     <- Chinese glossary
├── glossary_ne.json        <- Nepali glossary
├── church_glossary.json    <- 100 Urdu church terms
└── templates/
    ├── index.html          <- Control panel
    └── glossary.html       <- Glossary manager
```