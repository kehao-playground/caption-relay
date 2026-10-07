# Caption Relay: AI Agent Guide

This file is for coding agents and maintainers. Follow it before changing runtime code.

## Project identity

- Public name: **Caption Relay**.
- Python project name: `caption-relay`.
- Checkout directory: `caption-relay`.
- Python package: `caption_relay` in `src/caption_relay/`; console script `caption-relay`.
- Primary user path: `start.sh` -> `caption-relay` -> `caption_relay.cli:run`.

## Setup

```bash
uv sync --locked
export GEMINI_API_KEY="..."  # needed for live Gemini runs
./start.sh --help
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests routes scripts
```

Optional dependency groups:

```bash
uv sync --locked --extra offline
uv sync --locked --extra sherpa
uv sync --locked --extra whisperlive
```

For a network/API smoke run:

```bash
./start.sh --file fixtures/test_zh_paused16k.wav
```

Do not run a live microphone test unless the user requested it. It opens the selected PortAudio device and sends audio to Gemini.

## Runtime contract

1. `config.parse_args()` loads `captions.toml`, applies one-run CLI overrides, and returns a frozen `Config`.
2. `source = "auto"` becomes an empty Gemini language hint (`Config.language_codes`); a BCP-47 value becomes a single hint.
3. The audio source (`Microphone` or `WavFile`) is opened before the Gemini session so device and format errors fail fast.
4. The capture thread turns `audio_events()` (100 ms `AudioChunk`, `UtteranceEnd` after silence, `StreamEnd`) into Gemini Live input. Capture failures propagate to the session instead of hanging it.
5. `GeminiLiveTranscriber` emits `SessionStatus`, `InterimText`, and `FinalTranscript` events only.
6. `CaptionCoordinator` gives each finalized utterance a sequential caption ID and receive time (`FinalText`) and starts a bounded-concurrency translation through the `Translator` protocol.
7. Each translation ends in exactly one `TranslationReady` or `TranslationFailed` for its caption ID; an empty translation is a failure.
8. `CaptionDisplay.handle()` keeps the newest source preview visible until that exact translation completes.
9. Translation completion replaces only its own source preview; out-of-order completions must not overwrite newer text, and the metadata column keeps each caption's own number.
10. Terminal decorations are disabled for redirected output; the optional metadata column remains as plain text.

## File ownership

| File | Responsibility | Do not add |
|---|---|---|
| `src/caption_relay/cli.py` | Entry point, credentials, audio-source selection, session lifetime | Protocol details or rendering |
| `src/caption_relay/config.py` | CLI parsing, TOML loading and validation, `Config` | I/O beyond reading the config file |
| `src/caption_relay/audio.py` | PortAudio microphone, ALSA quieting, WAV fixtures, audio events, silence detection | Network calls |
| `src/caption_relay/events.py` | Immutable event types shared across layers | Behavior or provider types |
| `src/caption_relay/coordinator.py` | Caption IDs, receive times, translation task lifetime and concurrency | Provider SDK imports, rendering |
| `src/caption_relay/translation.py` | `Translator` protocol and `TranslationRequest` | Provider implementations |
| `src/caption_relay/providers/gemini_live.py` | Gemini Live session, capture thread, transcription events | Translation, terminal output |
| `src/caption_relay/providers/gemini_text.py` | Gemini per-utterance translation (AFC disabled) | Retries, display calls |
| `src/caption_relay/renderers/terminal.py` | TTY/Kitty rendering, preview replacement, separators, metadata column | API calls, environment-specific model logic |
| `tests/test_terminal_renderer.py` | Kitty parser-backed display regressions driven by synthetic events | Tautological source-text tests |
| `tests/test_coordinator.py`, `tests/test_gemini_text.py` | Ordering, failure, and request-shape regressions with fakes | Network access |
| `tests/test_config.py`, `tests/test_audio.py` | Configuration and audio-input regressions | Network or live-device access |
| `captions.toml` | Safe project defaults | Secrets, host-specific absolute paths |
| `start.sh` | Stable launcher | Business logic |
| `routes/` | Optional comparison routes, each self-contained; `routes/README.md` is their index | Imports from or into `caption_relay` |
| `scripts/` | Developer utilities such as fixture generation | Runtime code |
| `fixtures/`, `models/` | Local test audio and model files (ignored except text and README) | Committed binaries |
| `README.md` | Public usage and limitations | Unverified performance claims |
| `docs/REFACTORING.md` | Staged design plan | Completed implementation details presented as future work |

The offline and comparison scripts under `routes/` are intentionally separate routes. Reuse their existing behavior before changing them; do not silently make a Gemini privacy claim for a local route or vice versa.

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
- Check all callers when changing event types, `CaptionDisplay`, `CaptionCoordinator`, the `Translator` protocol, or configuration keys.
- Do not add retries, telemetry, persistence, or abstractions unless the task requires them.
- Keep the terminal renderer backend-agnostic. Kitty-specific escape sequences belong behind renderer helpers.
- Do not add a second configuration format.
- Do not commit generated audio, model files, ad-hoc screenshots, smoke scripts, logs, or secrets. The only committed images are the README screenshots in `docs/images/`; regenerate them with the procedure below instead of adding new ones casually.
- Use Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`; optional scope such as `feat(display):`).

## Verification matrix

Run the smallest relevant checks, then the full display suite for renderer changes:

```bash
uv run python -m compileall -q src tests routes scripts
uv run python -m unittest discover -s tests -v
./start.sh --help
uv run python - <<'PY'
from caption_relay.config import parse_args
args = parse_args([])
assert args.source_language == "auto"
assert args.destination_language == "en"
print("configuration smoke passed")
PY
```

For changes to the live route, run the fixture only when credentials are available and report whether the observed output completed normally. For UI changes, launch a real Kitty preview and inspect it; parser tests alone are not visual proof.

## README screenshots

`docs/images/bilingual.png` and `docs/images/replacement.png` use the fixture with the README commands. To regenerate them, run the README commands in a Kitty window with `-o background_opacity=1 -o background_image=none`, hide the cursor (`printf '\033[?25l'` before `./start.sh`), capture the window, then trim and compress:

```bash
magick shot.png -fuzz 3% -trim +repage -bordercolor "srgb(40,42,54)" -border 36 \
  -strip -dither None -colors 128 -define png:compression-level=9 docs/images/<name>.png
```

Use the terminal background color for the border. For `bilingual.png`, use a temporary config with `show_zh = true`; do not commit it. Capture `replacement.png` mid-run so a Chinese preview is visible. Keep the images unedited apart from cropping.

## Known limitations

- Gemini Live transcription does not provide speaker diarization or word-level timestamps.
- Optional timestamps are application receive times of finalized text, not word timings.
- Scaled captions wrap at character boundaries, not word boundaries.
- The Gemini route uploads audio and finalized text.
- Kitty enlarged text uses terminal grid rows; `1.0` is the dense default.
- Translation tasks are concurrent, so display code must handle out-of-order completion.

## Completion checklist

Before delivery:

- All affected callers, tests, docs, and config examples agree.
- No stale old project name remains in public metadata or the main README unless describing migration history.
- Runtime messages are English.
- `uv run python -m compileall -q src tests routes scripts` passes.
- Relevant tests pass.
- A changed interactive surface has been exercised in Kitty or the limitation is explicitly reported.
