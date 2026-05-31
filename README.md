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
                    Transmitter -> Earpieces
```

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