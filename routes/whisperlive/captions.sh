#!/usr/bin/env bash
# WhisperLive 內建中→英翻譯比較路線（終端機字幕）。
# 用法: ./captions.sh [model] [--file /path/to/audio.wav]，預設 medium。
set -euo pipefail
MODEL="${1:-medium}"
if (( $# )); then shift; fi
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$HERE/../.." && pwd)"
exec uv run --project "$ROOT" --extra whisperlive python \
  "$HERE/translate.py" --model "$MODEL" "$@"
