#!/usr/bin/env bash
# Gemini Live 中文辨識 + 逐句英譯；可傳 --file /path/to/audio.wav。
set -euo pipefail
BASE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$BASE" python "$BASE/captions_gemini.py" "$@"
