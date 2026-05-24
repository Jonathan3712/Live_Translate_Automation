# 🎙 Live Stage Transcription System
**Mic → English on big screen → Urdu translation → Urdu spoken aloud**

---

## What This Does
1. Captures audio from your Mac mic (or mixer later)
2. Sends it to **OpenAI Whisper** → transcribes to English
3. Sends English to **Claude (Haiku)** → translates to Urdu
4. Speaks the Urdu via **gTTS** (free) or ElevenLabs (optional)
5. Displays everything live on a full-screen browser page you project on the big screen

---

## Setup (One Time Only)

### Step 1 — Get API Keys

**OpenAI** (for Whisper transcription)
- Go to https://platform.openai.com/api-keys
- Create account → Add $5 credit → Create API key
- Copy the key (starts with `sk-`)

**Anthropic / Claude** (for Urdu translation)
- You already have this — find it at https://console.anthropic.com/settings/keys

### Step 2 — Create your .env file
```bash
cp .env.example .env
```
Open `.env` in any text editor and fill in:
```
OPENAI_API_KEY=sk-...your key...
ANTHROPIC_API_KEY=sk-ant-...your key...
```

### Step 3 — Run
```bash
chmod +x run.sh
./run.sh
```
That's it. The script installs everything automatically.

---

## Using It at an Event

1. **Run** `./run.sh` on your Mac
2. Open **http://localhost:5050** → Control Panel (your screen)
3. Open **http://localhost:5050/display** → Big Screen view
4. **Project the /display tab** via HDMI/AirPlay to the big screen
5. Click **▶ Start** in the control panel
6. Speak into the mic — transcription appears on the big screen every ~6 seconds

---

## Switching to Mixer Output (Later)

When you connect venue audio via a mixer:
1. Go to **System Preferences → Sound → Input**
2. Select your audio interface / mixer input
3. The app picks up whatever Mac's default input is — no code change needed

---

## Cost Per Event (2-hour event)

| Service | Cost |
|---|---|
| Whisper API (~120 min audio) | ~$0.43 |
| Claude Haiku (translation) | ~$0.10 |
| gTTS (Urdu speech) | $0.00 |
| **Total** | **~$0.53** |

---

## Troubleshooting

**"pyaudio not found"**
```bash
brew install portaudio
pip3 install pyaudio
```

**"OPENAI_API_KEY missing"**
→ Check your .env file has no extra spaces around the `=`

**Urdu text not showing**
→ The Noto Nastaliq Urdu font loads from Google Fonts — needs internet on display device

**Audio not playing on big screen**
→ Click anywhere on the /display page first (browser needs a user gesture for audio autoplay)

**Too much silence being transcribed**
→ Whisper filters silence, but if getting empty results, move mic closer to speaker

---

## File Structure
```
live-transcribe/
├── app.py              ← Main Python server
├── requirements.txt    ← Python dependencies
├── run.sh              ← Mac launcher script
├── .env.example        ← API key template
├── .env                ← Your actual keys (never commit this)
└── templates/
    ├── index.html      ← Control panel
    └── display.html    ← Big screen display
```

---

## Upgrading to ElevenLabs (Better Urdu Voice)
1. Create free account at https://elevenlabs.io
2. Get API key from Profile → API Keys
3. Add to `.env`:
   ```
   ELEVENLABS_API_KEY=your-key-here
   ```
4. Restart — app auto-detects and uses ElevenLabs instead of gTTS
