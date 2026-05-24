#!/bin/bash
# ─────────────────────────────────────────────────────────
#  Live Transcription System — Mac Launcher
#  Usage: ./run.sh
# ─────────────────────────────────────────────────────────

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Load .env if present
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
  echo "✓ Loaded .env"
else
  echo "⚠  No .env file found. Copy .env.example → .env and fill in keys."
  exit 1
fi

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "✗ python3 not found. Install from https://python.org"
  exit 1
fi

# Install deps if needed
echo "→ Checking dependencies..."
pip3 install -q -r requirements.txt

# On Mac, pyaudio sometimes needs portaudio
if ! python3 -c "import pyaudio" 2>/dev/null; then
  echo "→ Installing portaudio via Homebrew (needed for pyaudio on Mac)..."
  if command -v brew &>/dev/null; then
    brew install portaudio
    pip3 install pyaudio
  else
    echo "⚠  Homebrew not found. Install it: https://brew.sh, then run: brew install portaudio && pip3 install pyaudio"
    exit 1
  fi
fi

echo ""
echo "🚀 Starting server..."
echo "   Control panel → http://localhost:5050"
echo "   Big screen    → http://localhost:5050/display"
echo ""

python3 app.py
