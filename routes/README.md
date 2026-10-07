# Comparison routes

These scripts predate the `caption_relay` package. They are kept for latency and quality comparisons and are not wired into the primary route. Run them from the checkout with the matching dependency extra; model files go in `../models/` (see [`models/README.md`](../models/README.md)).

| Route | Command | Extra | Recognition | Translation | Leaves the machine |
|---|---|---|---|---|---|
| Offline Whisper | `uv run --extra offline python routes/offline/captions_offline.py [--file x.wav]` | `offline` | faster-whisper per VAD-segmented utterance (local) | Gemini text if `GEMINI_API_KEY` is set | Finalized text only, when the key is set |
| sherpa-onnx | `uv run --extra sherpa python routes/sherpa/captions_live.py [--model para] [--file x.wav]` | `sherpa` | sherpa-onnx streaming zipformer or paraformer (local) | Gemini text if `GEMINI_API_KEY` is set | Finalized text only, when the key is set |
| WhisperLive + Gemini | `routes/whisperlive/serve.sh`, then `uv run --extra whisperlive python routes/whisperlive/live_zh2en.py` | `whisperlive` | WhisperLive server on `localhost:9090` | Gemini text if `GEMINI_API_KEY` is set | Finalized text only, when the key is set |
| WhisperLive built-in | `routes/whisperlive/serve.sh`, then `routes/whisperlive/captions.sh [model] [--file x.wav]` | `whisperlive` | WhisperLive server on `localhost:9090` | Whisper's built-in translate task | Nothing |

Without `GEMINI_API_KEY`, the first three routes show source-language text only and run fully locally.

Route-specific environment variables:

| Variable | Routes | Default |
|---|---|---|
| `WL_MODEL` | offline, WhisperLive + Gemini | `medium` |
| `WL_TASK` | offline | `transcribe` |
| `GEMINI_MODEL` | offline, sherpa-onnx | `gemini-2.5-flash-lite` |
| `GEMINI_MODEL` | WhisperLive + Gemini | `gemini-2.5-flash` |

Manual probes (not unit tests):

- `routes/sherpa/probe_stream.py [x.wav]`: streaming decode with endpointing; reports worst per-step decode time.
- `routes/sherpa/probe_whole.py x.wav`: decode a whole file at once.
- `routes/whisperlive/probe_hotwords.py [model]`: WhisperLive translation with hotwords against `fixtures/test_zh.wav`.

Their user-facing text is Chinese and they share a duplicated Gemini REST helper; porting them into `caption_relay` is out of scope (see `docs/REFACTORING.md`, "Non-goals").
