#!/usr/bin/env bash
# Run pylint the same way as GitHub Actions (.github/workflows/pylint.yml).
#
# Usage:
#   ./scripts/run_pylint.sh          # check only
#   ./scripts/run_pylint.sh --fix    # auto-fix style, then check

set -euo pipefail

FIX=false
if [ "${1:-}" = "--fix" ]; then
  FIX=true
elif [ -n "${1:-}" ]; then
  echo "Usage: $0 [--fix]"
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -f ".venv/bin/activate" ]; then
  # shellcheck source=/dev/null
  source ".venv/bin/activate"
elif [ -f "venv/bin/activate" ]; then
  # shellcheck source=/dev/null
  source "venv/bin/activate"
else
  echo "No venv found (.venv/ or venv/). Using current Python: $(command -v python3 || command -v python)"
  echo "Tip: create a venv first — python3 -m venv .venv && source .venv/bin/activate"
fi

PYTHON="$(command -v python3 || command -v python)"

echo "Installing lint tools and project dependencies..."
"$PYTHON" -m pip install --upgrade pip -q
"$PYTHON" -m pip install pylint autopep8 -q
if [ -f requirements.txt ]; then
  if ! "$PYTHON" -m pip install -r requirements.txt -q; then
    echo "Warning: full requirements install failed (PyAudio often needs portaudio)."
    echo "  macOS: brew install portaudio"
    echo "  Ubuntu: sudo apt-get install portaudio19-dev"
    echo "Continuing; import checks may fail for missing packages."
  fi
fi

PY_FILES=()
while IFS= read -r f; do
  [ -n "$f" ] && PY_FILES+=("$f")
done <<EOF
$(git ls-files '*.py')
EOF
if [ "${#PY_FILES[@]}" -eq 0 ]; then
  echo "No Python files tracked by git."
  exit 0
fi

if [ "$FIX" = true ]; then
  echo "Auto-fixing style issues with autopep8..."
  "$PYTHON" -m autopep8 --in-place --max-line-length=100 --aggressive --aggressive "${PY_FILES[@]}"
  echo "Ensuring each file ends with a newline..."
  for f in "${PY_FILES[@]}"; do
    "$PYTHON" -c "import pathlib, sys; p=pathlib.Path(sys.argv[1]); t=p.read_text(encoding='utf-8'); p.write_text(t if t.endswith('\n') else t + '\n', encoding='utf-8')" "$f"
  done
fi

echo "Running pylint on ${#PY_FILES[@]} file(s)..."
"$PYTHON" -m pylint "${PY_FILES[@]}"
