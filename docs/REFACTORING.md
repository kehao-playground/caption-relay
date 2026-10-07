# Caption Relay Refactoring Roadmap

This is an implementation plan, not a claim that the stages are complete. Keep each stage independently reviewable and behavior-preserving.

## Current baseline

- The primary route is the `caption_relay` package in `src/caption_relay/`, launched through the `caption-relay` console script.
- `config.py` parses CLI and TOML into a frozen `Config`; `audio.py` owns microphone and WAV input; `gemini.py` combines Gemini Live transport and translation scheduling; `cli.py` owns process lifecycle.
- `display.py` is a separate terminal renderer with Kitty-backed tests.
- `captions.toml` contains display, language, and audio defaults.
- The primary fixture completes six finalized English captions.
- Translation tasks may complete out of order; caption IDs protect replacement state.

## Stage 1: Stabilize contracts

**Goal:** make current behavior explicit before moving code.

- Introduce typed configuration objects for display, language, and audio settings.
- Keep `parse_args()` as the only CLI/config boundary.
- Add tests for missing sections, invalid values, CLI precedence, `source = "auto"`, and device selection errors.
- Preserve English runtime messages and the current `captions.toml` schema.

**Exit criteria:** configuration tests cover every public key; no caller reads TOML directly.

**Status:** mostly done. `Config` is a single frozen dataclass (not one object per section) and `tests/test_config.py` covers defaults, missing sections, invalid values, CLI precedence, and `source = "auto"`. Remaining: a device-selection error test that mocks PyAudio.

## Stage 2: Define backend events

**Goal:** decouple Gemini from terminal rendering.

Create small internal event types, for example:

```text
InterimText(text)
FinalText(id, text, received_at)
TranslationReady(id, text)
TranslationFailed(id, error)
SessionStatus(message)
```

- The Gemini receiver emits events.
- A coordinator owns translation task lifetime and ordering metadata.
- `CaptionDisplay` consumes events and remains unaware of Gemini response models.
- Keep the current output behavior during the migration.

**Exit criteria:** display tests can run with synthetic events and no Google SDK import.

## Stage 3: Audio input abstraction

**Goal:** make microphone and fixture input interchangeable.

- Define an audio-source interface yielding PCM chunks and an explicit end event.
- Implement `MicrophoneSource` using PortAudio and `WavSource` using `wave`.
- Keep device discovery and ALSA handling inside the microphone implementation.
- Test invalid WAV format and missing device behavior without opening a live API session.

**Exit criteria:** the session coordinator no longer branches deeply on `args.file`.

**Status:** mostly done. `audio.Microphone` and `audio.WavFile` share a `chunks()`/`close()` shape, are opened before the session, and `gemini.run_session()` does not branch on the source type. `tests/test_audio.py` covers invalid WAV formats and silence detection. Remaining: a missing-device test without PortAudio hardware, and an explicit end event instead of generator exhaustion.

## Stage 4: Translation provider abstraction

**Goal:** isolate the per-utterance translation service.

- Define an async translator protocol: finalized source text -> destination text.
- Implement Gemini text translation with AFC disabled.
- Make destination language an explicit request field, not only prompt interpolation.
- Preserve bounded concurrency and error reporting.

**Exit criteria:** coordinator tests use a deterministic fake translator; no network is needed to test replacement ordering.

## Stage 5: Renderer capabilities

**Goal:** support optional metadata without coupling it to layout code.

- Add optional line number and receive-time timestamp fields to a renderer model.
- Render metadata as a left column with a calculated width.
- Keep separator rules independent from metadata.
- Do not claim word-level timestamps when only receive time is available.

**Exit criteria:** line numbers remain stable under out-of-order translation; wrapped lines do not receive duplicate numbers or separators.

## Stage 6: Backend registry and package layout

**Goal:** make comparison routes discoverable without making the primary script larger.

Possible layout:

```text
caption_relay/
  cli.py
  config.py
  events.py
  audio.py
  providers/
    gemini_live.py
    gemini_text.py
  renderers/
    terminal.py
  backends/
    offline_whisper.py
    sherpa.py
```

**Status:** the package layout, `caption-relay` entry point, and `routes/` separation are done; old root script paths were removed in one cutover. The `events`, `providers/`, `renderers/`, and `backends/` split remains future work and still depends on Stages 2, 4, and 5.

- Move only after Stages 1–5 have stable tests.
- Keep `start.sh` as a compatibility launcher.
- Update imports and docs in one cutover; do not leave duplicate implementations or shims.

**Exit criteria:** `uv run caption-relay` or an equivalent documented entry point is the canonical command, and old script paths are either removed or explicitly comparison-only.

## Non-goals unless requested

- Speaker diarization in Gemini Live: the API does not support it for live streaming.
- Word-level timestamps in Gemini Live: not available in the current live route.
- Automatic retries or persistent transcript storage.
- GUI/overlay rendering.
- Rewriting all legacy comparison backends during the primary-route refactor.

## Review risks

- Concurrent translation can expose cursor-state bugs; every replacement must use an utterance ID.
- Kitty multicell text can consume more grid rows than normal text; renderer tests must include narrow terminal widths.
- A config migration can silently change privacy or language behavior; preserve defaults and document every changed default.
- “English logs” must not translate caption content or provider-returned user text.
