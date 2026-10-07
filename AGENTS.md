# Caption Relay: AI Agent Guide

This file is for coding agents and maintainers. Follow it before changing runtime code.

## Project identity

- Public name: **Caption Relay**.
- Python project name: `caption-relay`.
- Checkout directory: `caption-relay`.
- Primary user path: `start.sh` -> `captions_gemini.py`.

## Setup

```bash
uv sync --locked
export GEMINI_API_KEY="..."  # needed for live Gemini runs
./start.sh --help
uv run python -m unittest -v test_caption_display.py
python -m py_compile captions_gemini.py caption_display.py test_caption_display.py
```

Optional dependency groups:

```bash
uv sync --locked --extra offline
uv sync --locked --extra sherpa
uv sync --locked --extra whisperlive
```

For a network/API smoke run:

```bash
./start.sh --file test_zh_paused16k.wav
```

Do not run a live microphone test unless the user requested it. It opens the selected PortAudio device and sends audio to Gemini.

## Runtime contract

1. `parse_args()` loads `captions.toml` and applies one-run CLI overrides.
2. `source = "auto"` becomes an empty Gemini language hint; a BCP-47 value becomes a single hint.
3. `capture()` sends 16 kHz mono PCM in 100 ms chunks and emits an audio-stream end after silence.
4. Gemini emits interim and finalized input transcription events.
5. Each finalized utterance receives an opaque caption ID and an asynchronous translation task.
6. `CaptionDisplay` keeps the newest source preview visible until that exact translation completes.
7. Translation completion replaces only its own source preview; out-of-order completions must not overwrite newer text.
8. Terminal decorations are disabled for redirected output.

## File ownership

| File | Responsibility | Do not add |
|---|---|---|
| `captions_gemini.py` | CLI, config, Gemini sessions, capture, task lifecycle | Terminal cursor algorithms or duplicated rendering logic |
| `caption_display.py` | TTY/Kitty rendering, preview replacement, separators | API calls, environment-specific model logic |
| `captions.toml` | Safe project defaults | Secrets, host-specific absolute paths |
| `test_caption_display.py` | Kitty parser-backed display regressions | Tautological source-text tests |
| `start.sh` | Stable launcher | Business logic |
| `README.md` | Public usage and limitations | Unverified performance claims |
| `REFACTORING.md` | Staged design plan | Completed implementation details presented as future work |

The offline and comparison scripts are intentionally separate routes. Reuse their existing behavior before changing them; do not silently make a Gemini privacy claim for a local route or vice versa.

## Configuration rules

- Keep runtime logs and errors in English.
- Preserve user-facing caption language from configuration.
- Validate TOML types and values at startup; fail with an actionable message.
- Add a new setting to `captions.toml`, `parse_args()`, README, and tests together.
- Prefer stable BCP-47 values for language codes. Human-readable destination names are allowed in the translation prompt.
- `audio.input_device` is a case-insensitive name fragment. The `pipewire` default is intentional for this workstation, not a universal hardware name.
- ALSA probe noise may be suppressed only around PortAudio enumeration. Never suppress a real stream-open exception.

## Change discipline

- Read the affected file before editing; use surgical edits for existing code.
- Check all callers when changing `CaptionDisplay`, `translate`, or configuration keys.
- Do not add retries, telemetry, persistence, or abstractions unless the task requires them.
- Keep the terminal renderer backend-agnostic. Kitty-specific escape sequences belong behind renderer helpers.
- Do not add a second configuration format.
- Do not commit generated audio, model files, screenshots, smoke scripts, logs, or secrets.

## Verification matrix

Run the smallest relevant checks, then the full display suite for renderer changes:

```bash
python -m py_compile captions_gemini.py caption_display.py test_caption_display.py
uv run python -m unittest -v test_caption_display.py
./start.sh --help
uv run python - <<'PY'
from captions_gemini import parse_args
args = parse_args([])
assert args.source_language == "auto"
assert args.destination_language == "en"
print("configuration smoke passed")
PY
```

For changes to the live route, run the fixture only when credentials are available and report whether the observed output completed normally. For UI changes, launch a real Kitty preview and inspect it; parser tests alone are not visual proof.

## Known limitations

- Gemini Live transcription does not provide speaker diarization or word-level timestamps.
- Application-level line numbers and receive-time timestamps are not implemented yet.
- The Gemini route uploads audio and finalized text.
- Kitty enlarged text uses terminal grid rows; `1.0` is the dense default.
- Translation tasks are concurrent, so display code must handle out-of-order completion.

## Completion checklist

Before delivery:

- All affected callers, tests, docs, and config examples agree.
- No stale old project name remains in public metadata or the main README unless describing migration history.
- Runtime messages are English.
- `python -m py_compile ...` passes.
- Relevant tests pass.
- A changed interactive surface has been exercised in Kitty or the limitation is explicitly reported.
