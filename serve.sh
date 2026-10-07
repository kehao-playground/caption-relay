#!/usr/bin/env bash
# WhisperLive 字幕伺服器：本機 9090 port，模型依 client 端指定
set -euo pipefail
BASE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$BASE" --extra whisperlive python \
  "$BASE/whisperlive_server.py" "$@"
