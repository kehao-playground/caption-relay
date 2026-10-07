#!/usr/bin/env bash
# Gemini Live 中文辨識 + 逐句英譯；可傳 --file fixtures/test_zh_paused16k.wav。
set -euo pipefail
BASE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$BASE" caption-relay "$@"
