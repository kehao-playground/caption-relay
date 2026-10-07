# Caption Relay

Terminal-first live speech captioning and translation.

Caption Relay streams microphone audio to a transcription backend, turns finalized source-language utterances into destination-language captions, and renders them in a split terminal such as Kitty. The default backend is Gemini Live; local Whisper and sherpa-onnx routes remain available for comparison and offline work.

Caption Relay is the public project name and the checkout directory is `caption-relay`.

## Features

- Gemini Live low-latency transcription with interim and finalized text.
- Configurable source language (`auto` by default) and destination language (`en` by default).
- Chinese preview that is replaced by the finalized translation when `show_zh = false`.
- Normal-size terminal captions by default; optional Kitty text scaling remains supported.
- English captions without an artificial `EN` prefix.
- Low-contrast separators between completed captions; wrapped lines do not receive extra separators.
- PortAudio input selection by device-name fragment, with PipeWire as the default.
- English runtime logs and configuration errors for public-project usability.
- Optional local Whisper, sherpa-onnx, and WhisperLive comparison routes.

## Quick start

Requirements:

- Linux/macOS with Python 3.12.
- [`uv`](https://docs.astral.sh/uv/).
- PortAudio development packages for microphone use. On Arch Linux:

  ```bash
  sudo pacman -S --needed portaudio base-devel
  ```

Install and run:

```bash
uv sync --locked
export GEMINI_API_KEY="your-api-key"
./start.sh
```

Run the deterministic fixture instead of a microphone:

```bash
./start.sh --file test_zh_paused16k.wav
```

The fixture must be 16 kHz, mono, 16-bit PCM WAV. `start.sh` resolves the Python project from its own location, so it can be launched from another working directory.

## Configuration

`captions.toml` is the user-facing configuration file. It is read relative to the project directory by default.

```toml
[display]
zh_scale = 1.0
en_scale = 1.0
show_zh = false

[languages]
source = "auto"
destination = "en"

[audio]
input_device = "pipewire"
```

### Language

- `languages.source`: `auto` or a BCP-47 code such as `zh-TW`.
- `languages.destination`: a language code or name used in the translation request; default `en`.
- One-run overrides: `--source-language`, `--destination-language`.

Gemini Live does not provide speaker diarization or word-level timestamps in its live streaming route. Those features require a non-streaming transcription workflow. Caption Relay can add application-level line numbers or receive-time timestamps later without changing the transcription protocol.

### Display

- `zh_scale` and `en_scale`: `0.5`, `1.0`, `1.2`, or `1.5`. `1.0` is recommended for dense terminal layouts.
- `show_zh = false`: show Chinese interim/final text temporarily, then replace that utterance with the translation. If translation fails, the source preview and an English error remain visible.
- Kitty 0.40+ supports the text sizing protocol used by scaled captions. Scaled text occupies terminal grid rows; `1.0` avoids the extra row required by enlarged text.
- In interactive terminals, completed captions are separated by a subtle gray rule. Redirected output omits terminal decoration.

### Audio

`audio.input_device` is matched case-insensitively against PortAudio input-device names. Use a fragment such as `pipewire`, `ALC257 Analog`, or `Stereo Microphone`.

The launcher suppresses harmless ALSA diagnostics emitted while PortAudio probes unavailable profiles. A real device-selection or stream-opening failure is not suppressed.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | Gemini API key; required for the Gemini route |
| `GEMINI_LIVE_MODEL` | `gemini-3.5-transcribe-live` | Live transcription model |
| `GEMINI_XLATE_MODEL` | `gemini-flash-lite-latest` | Finalized-utterance translation model |
| `WL_VOCAB` | empty | Comma-separated recognition terms |

Runtime status, configuration errors, audio errors, and translation errors are emitted in English. Audio and finalized text are sent to Gemini in the Gemini route; do not describe this route as offline.

## Architecture

```text
start.sh
  -> captions_gemini.py
       -> Gemini Live transcription session
       -> CaptionDisplay (terminal state, replacement, separators)
       -> Gemini text translation per finalized utterance
       -> Kitty/TTY output
```

Important boundaries:

- `captions_gemini.py` owns configuration, audio capture, network sessions, and task coordination.
- `caption_display.py` owns terminal rendering only. It must not call Gemini or read API keys.
- `captions.toml` owns user-selectable language, audio, and display defaults.
- `test_caption_display.py` exercises terminal transitions through Kitty's parser, not source-string snapshots.

Comparison routes:

- `captions_offline.py`: VAD plus faster-whisper.
- `captions_live.py`: sherpa-onnx streaming recognition.
- `live_zh2en.py`, `captions.sh`, and `serve.sh`: WhisperLive comparison paths.

## Development setup

```bash
uv sync --locked
uv run python -m unittest -v test_caption_display.py
python -m py_compile captions_gemini.py caption_display.py test_caption_display.py
./start.sh --help
```

For optional backends:

```bash
uv sync --locked --extra offline
uv sync --locked --extra sherpa
uv sync --locked --extra whisperlive
```

Do not commit API keys, recordings, model files, virtual environments, generated output, or machine-specific configuration. `.gitignore` already excludes the current local-only artifacts; review it before publishing a new fixture.

## Verification status

The primary Gemini route has been exercised with the bundled 38.7-second fixture and produced six finalized English captions. The microphone path has been opened successfully through the configured PipeWire device. The terminal renderer has 17 Kitty-backed regression tests covering replacement ordering, separators, wrapping, narrow splits, mixed-width text, redirected output, and failure retention.

The following are not promises: microphone quality in every environment, exact semantic translation quality, speaker identity, word-level timing, or offline privacy for the Gemini route.

## Refactoring roadmap

See [`REFACTORING.md`](REFACTORING.md) for staged changes. The safe next boundary is separating backend events from terminal rendering; do not mix that migration with a model or display redesign.

## AI-assisted maintenance

See [`AGENTS.md`](AGENTS.md). It is the source of truth for agent setup, architecture boundaries, verification commands, and change discipline.

## Security and privacy

Never commit `api.key`, `GEMINI_API_KEY`, `.env` files, audio recordings, or model artifacts. Gemini Live uploads audio and text to Google's service. This repository is licensed under the MIT License; add a contribution and security contact before public release if the hosting platform does not provide one.
