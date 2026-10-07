"""Command-line and captions.toml configuration."""
import argparse
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Source checkout root: src/caption_relay/config.py -> project directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "captions.toml"

CAPTION_SCALES = (0.5, 1.0, 1.2, 1.5)
LANGUAGE_AUTO = "auto"
DEFAULT_SOURCE_LANGUAGE = LANGUAGE_AUTO
DEFAULT_DESTINATION_LANGUAGE = "en"
DEFAULT_INPUT_DEVICE = "pipewire"


@dataclass(frozen=True)
class Config:
    config: str
    file: str | None
    zh_scale: float
    en_scale: float
    show_zh: bool
    source_language: str
    destination_language: str
    audio_device: str

    @property
    def language_codes(self):
        """Gemini language hints: none for auto, otherwise the single BCP-47 code."""
        return [] if self.source_language.lower() == LANGUAGE_AUTO else [self.source_language]


def _table(config, name):
    table = config.get(name, {})
    if not isinstance(table, dict):
        raise ValueError(f"{name} must be a TOML table")
    return table


def _text(value, message):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(message)
    return value


def _build_parser():
    ap = argparse.ArgumentParser(
        prog="caption-relay",
        description="Live speech captions with Gemini Live transcription and per-utterance translation.")
    ap.add_argument("--file", help="Stream a 16 kHz mono 16-bit WAV file instead of the microphone")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="Configuration file (default: project captions.toml)")
    ap.add_argument("--zh-scale", type=float, choices=CAPTION_SCALES,
                    help="Override Chinese caption scale")
    ap.add_argument("--en-scale", type=float, choices=CAPTION_SCALES,
                    help="Override destination caption scale")
    ap.add_argument("--source-language", help="Override source language (auto or BCP-47 code)")
    ap.add_argument("--destination-language", help="Override destination language (BCP-47 code or name)")
    return ap


def parse_args(argv=None):
    """Load captions.toml, apply one-run CLI overrides, and validate the result."""
    ap = _build_parser()
    args = ap.parse_args(argv)
    try:
        with open(args.config, "rb") as config_file:
            config = tomllib.load(config_file)
        display = _table(config, "display")
        languages = _table(config, "languages")
        audio = _table(config, "audio")

        scales = {}
        for name in ("zh_scale", "en_scale"):
            value = display.get(name, 1.0)
            if isinstance(value, bool) or value not in CAPTION_SCALES:
                raise ValueError(f"display.{name} must be one of {CAPTION_SCALES}")
            override = getattr(args, name)
            scales[name] = float(value if override is None else override)

        show_zh = display.get("show_zh", True)
        if not isinstance(show_zh, bool):
            raise ValueError("display.show_zh must be true or false")

        source = _text(args.source_language or languages.get("source", DEFAULT_SOURCE_LANGUAGE),
                       "languages.source must be auto or a BCP-47 code")
        destination = _text(args.destination_language or languages.get("destination", DEFAULT_DESTINATION_LANGUAGE),
                            "languages.destination must be a BCP-47 code or name")
        device = _text(audio.get("input_device", DEFAULT_INPUT_DEVICE),
                       "audio.input_device must be a device name fragment")
    except (OSError, ValueError, tomllib.TOMLDecodeError) as e:
        ap.error(f"Configuration {args.config}: {e}")
    return Config(config=args.config, file=args.file, show_zh=show_zh,
                  source_language=source, destination_language=destination,
                  audio_device=device, **scales)
