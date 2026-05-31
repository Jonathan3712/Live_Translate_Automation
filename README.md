# 🎙 Live Stage Transcription System

Real-time speech transcription and translation for live events, churches, and conferences.

**Speaker talks in English → transcribed by Whisper → translated → spoken in target language**

Works on **Mac**, **Windows**, and **Linux** from the same codebase.

---

## How It Works

```
Stage mic → Mixer → USB → Mac/PC
                            ↓
                    OpenAI Whisper
                    (speech to English text)
                            ↓
                    Google Translate
                    (English → selected language)
                            ↓
                    gTTS / ElevenLabs
                    (text → spoken audio)
                            ↓
                    Transmitter → Wireless earpieces
                    (audience hears in their language)
```

---

## Features

- 11 languages supported — switch between them from the control panel
- Locked glossary per language — specific terms always translate consistently
- Voice Activity Detection — only records when someone is speaking
- Works with microphone, mixer (USB), or Zoom audio (via VB-Cable)
- Runs entirely in your browser at `http://localhost:5050`

---

## Cost

| Service | Cost |
|---|---|
| OpenAI Whisper (transcription) | ~$0.006/min (~$0.43 per 2hr event) |
| Google Translate | Free |
| gTTS (text-to-speech) | Free |
| **Total per Sunday service** | **~$0.43** |
| ElevenLabs (optional better voice) | $5–22/month |

---

## Supported Languages

| Language | Code |
|---|---|
| Urdu | ur |
| Chinese (Mandarin) | zh-CN |
| Nepali | ne |
| Hindi | hi |
| Arabic | ar |
| Spanish | es |
| French | fr |
| Turkish | tr |
| Portuguese | pt |
| Swahili | sw |
| Punjabi | pa |

---

## Requirements

### All platforms need:
- Python 3.11 — recommended (3.12 works, 3.13+ may have pyaudio issues)
- Git
- OpenAI API key — get one at https://platform.openai.com/api-keys

### Platform-specific:
| | Mac | Windows | Linux |
|---|---|---|---|
| Extra install | `brew install portaudio` | nothing | `sudo apt install portaudio19-dev mpg123 -y` |
| Audio playback | afplay (built-in) | winsound (built-in) | mpg123 |
| pyaudio | `pip install pyaudio` | needs wheel (see below) | `pip install pyaudio` |

---

## Setup — Mac

```bash
# 1. Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Install Python 3.11 and portaudio
brew install python@3.11 portaudio

# 3. Clone the repo
git clone https://github.com/Jonathan3712/live-transcribe.git
cd live-transcribe

# 4. Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# 5. Install dependencies
pip install -r requirements.txt

# 6. Create .env file
cp .env.example .env
nano .env
# Add: OPENAI_API_KEY=sk-...your key...

# 7. Run
python3 app.py
```

Open **http://localhost:5050** in your browser.

---

## Setup — Windows

### Before you start
- Download **Python 3.11** from https://python.org/downloads/release/python-3119
  - During install — check **Add Python to PATH**
- Download **Git** from https://git-scm.com

```bash
# 1. Clone the repo
git clone https://github.com/Jonathan3712/live-transcribe.git
cd live-transcribe

# 2. Create virtual environment using Python 3.11
py -3.11 -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create .env file
copy .env.example .env
notepad .env
# Add: OPENAI_API_KEY=sk-...your key...

# 5. Run
python app.py
```

Open **http://localhost:5050** in your browser.

### If pyaudio fails on Windows

Python 3.13+ doesn't have pyaudio wheels yet. Use Python 3.11 and try:

```bash
# Option A — pre-built wheel
# Download from: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
# Install (replace filename with your version):
pip install PyAudio-0.2.14-cp311-cp311-win_amd64.whl

# Option B — conda
conda install pyaudio
```

---

## Setup — Linux (Ubuntu / Debian)

```bash
# 1. Install system dependencies
sudo apt update
sudo apt install python3.11 python3.11-venv git portaudio19-dev mpg123 -y

# 2. Clone the repo
git clone https://github.com/Jonathan3712/live-transcribe.git
cd live-transcribe

# 3. Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Create .env file
cp .env.example .env
nano .env
# Add: OPENAI_API_KEY=sk-...your key...

# 6. Run
python3 app.py
```

Open **http://localhost:5050** in your browser.

---

## .env File

Create a `.env` file in the project root:

```
OPENAI_API_KEY=sk-...your-openai-key...

# Optional — natural sounding voice (better than gTTS)
# ELEVENLABS_API_KEY=your-elevenlabs-key
```

**Important:** Never upload your `.env` file to GitHub. It is listed in `.gitignore`.

---

## Verify Installation

Run this after `pip install -r requirements.txt` to confirm everything is installed:

```bash
pip list | grep -E "flask|openai|deep|gTTS|dotenv|pyaudio|requests"
```

You should see all 8 packages listed.

---

## Using a Mixer as Input

### Mac / Linux
1. Connect mixer to computer via USB
2. System Settings → Sound → Input → select your mixer
3. The app uses the system default input automatically

### Windows
1. Connect mixer via USB — Windows detects it
2. In the app's **Input Device** dropdown → select your mixer

---

## Using Zoom Audio as Input (Windows)

To transcribe a Zoom call:

1. Download **VB-Audio Virtual Cable** (free) from https://vb-audio.com/Cable
2. Install and restart Windows
3. In Zoom → Settings → Audio → **Speaker** → set to **CABLE Input**
4. To still hear Zoom yourself:
   - Control Panel → Sound → Recording → right-click **CABLE Output** → Properties
   - Listen tab → check **Listen to this device** → select your speakers → OK
5. In the app's Input Device dropdown → select **CABLE Output**

---

## Changing the Output Language

Click any language pill in the control panel before hitting **Start**.
Language locks while running — stop first to switch languages.

To change the **default** language, open `app.py` and find:
```python
"target_lang": "ur",
```
Change `ur` to any language code from the table above.

---

## Glossary — Locked Terms

Go to **http://localhost:5050/glossary** to manage locked translations.

- One tab per language
- Terms are always translated to your exact version — Google Translate cannot override them
- Import a JSON file to add many terms at once
- Export to back up or share your glossary

**Ready-to-import glossary files included in the repo:**
- `glossary_ur.json` — Urdu (10 church terms)
- `glossary_zh-CN.json` — Chinese
- `glossary_ne.json` — Nepali
- `glossary_hi.json` — Hindi
- `glossary_ar.json` — Arabic
- `glossary_es.json` — Spanish
- `glossary_fr.json` — French
- `glossary_tr.json` — Turkish
- `glossary_pt.json` — Portuguese
- `glossary_sw.json` — Swahili
- `glossary_pa.json` — Punjabi
- `church_glossary.json` — Full 100-term Urdu church glossary

**JSON format:**
```json
{
  "Holy Spirit": "روح القدس",
  "Jesus Christ": "یسوع مسیح",
  "Grace": "فضل"
}
```

---

## ElevenLabs — Better Voice Quality

gTTS sounds robotic. ElevenLabs sounds natural and human.

1. Create account at https://elevenlabs.io
2. Get API key from Profile → API Keys
3. Add to `.env`:
```
ELEVENLABS_API_KEY=your-key-here
```
4. Restart — app switches automatically

| Plan | Cost | Audio per month |
|---|---|---|
| Free | $0 | 10 min |
| Starter | $5 | 30 min |
| Creator | $22 | 100 min |

---

## Project Structure

```
live-transcribe/
├── app.py                    ← Main server (cross-platform)
├── requirements.txt          ← Python dependencies
├── .env.example              ← API key template
├── .env                      ← Your keys (never commit this)
├── README.md                 ← This file
├── church_glossary.json      ← 100 Urdu church terms (ready to import)
├── glossary_ur.json          ← Urdu glossary
├── glossary_zh-CN.json       ← Chinese glossary
├── glossary_ne.json          ← Nepali glossary
├── glossary_hi.json          ← Hindi glossary
├── glossary_ar.json          ← Arabic glossary
├── glossary_es.json          ← Spanish glossary
├── glossary_fr.json          ← French glossary
├── glossary_tr.json          ← Turkish glossary
├── glossary_pt.json          ← Portuguese glossary
├── glossary_sw.json          ← Swahili glossary
├── glossary_pa.json          ← Punjabi glossary
└── templates/
    ├── index.html            ← Control panel
    └── glossary.html         ← Glossary manager
```

---

## Tuning for Your Environment

In `app.py` inside `recording_thread()`:

```python
SILENCE_CHUNKS = 40    # Frames of silence before cutting
                       # Higher = waits longer after speech ends
                       # Lower = cuts sooner (good for fast speakers)

MAX_SECONDS    = 15    # Maximum recording length per chunk
```

In `is_speech()`:
```python
threshold = 400        # Lower = picks up softer voices
                       # Higher = ignores more background noise
```

---

## Troubleshooting

**OPENAI_API_KEY missing**
→ No spaces in `.env`: `OPENAI_API_KEY=sk-...` not `OPENAI_API_KEY = sk-...`

**pyaudio not installed on Mac**
→ `brew install portaudio` then `pip install pyaudio`

**pyaudio fails on Windows**
→ Use Python 3.11. Download pre-built wheel from lfd.uci.edu/~gohlke/pythonlibs

**pyaudio fails on Linux**
→ `sudo apt install portaudio19-dev` then `pip install pyaudio`

**Invalid input device on Windows**
→ Windows Sound Settings → Input → set a default microphone

**No audio playing on Linux**
→ `sudo apt install mpg123`

**Text shows but no audio**
→ Check internet — gTTS requires internet connection

**Sentences repeating**
→ Increase `SILENCE_CHUNKS` or move mic further from speakers

**Zoom audio not picked up**
→ Check VB-Cable is set as Zoom's Speaker, not just installed

---

## Quick Start Checklist

- [ ] Python 3.11 installed
- [ ] Git installed
- [ ] portaudio installed (Mac/Linux only)
- [ ] Repo cloned
- [ ] Virtual environment created and activated
- [ ] `pip install -r requirements.txt` completed
- [ ] `.env` file created with `OPENAI_API_KEY`
- [ ] `python app.py` running
- [ ] Browser open at http://localhost:5050
- [ ] Language selected
- [ ] Input device selected (if using mixer)
- [ ] **▶ Start** clicked