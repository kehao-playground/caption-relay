#!/usr/bin/env bash
# WhisperLive 字幕伺服器：本機 9090 port，模型依 client 端指定
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$HERE/../.." && pwd)"
exec uv run --project "$ROOT" --extra whisperlive python \
  "$HERE/server.py" "$@"
