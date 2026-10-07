#!/usr/bin/env bash
# WhisperLive 內建中→英翻譯比較路線（終端機字幕）。
# 用法: ./captions.sh [model] [--file /path/to/audio.wav]，預設 medium。
set -euo pipefail
MODEL="${1:-medium}"
if (( $# )); then shift; fi
BASE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$BASE" --extra whisperlive python \
  "$BASE/whisperlive_translate.py" --model "$MODEL" "$@"
