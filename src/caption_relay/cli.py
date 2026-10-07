"""Caption Relay entry point: configuration, credentials, audio source, and session."""
import asyncio
import os
import sys

from google import genai

from .audio import Microphone, WavFile
from .config import PROJECT_ROOT, parse_args
from .coordinator import CaptionCoordinator
from .events import SessionStatus
from .providers.gemini_live import GeminiLiveTranscriber
from .providers.gemini_text import GeminiTranslator
from .renderers.terminal import CaptionDisplay

LOGO = r"""
  ____            _   _               ____      _
 / ___|__ _ _ __ | |_(_) ___  _ __   |  _ \ ___| | __ _ _   _
| |   / _` | '_ \| __| |/ _ \| '_ \  | |_) / _ \ |/ _` | | | |
| |__| (_| | |_) | |_| | (_) | | | | |  _ <  __/ | (_| | |_| |
 \____\__,_| .__/ \__|_|\___/|_| |_| |_| \_\___|_|\__,_|\__, |
           |_|                                          |___/
"""


def print_logo():
    if sys.stdout.isatty():
        print(LOGO, end="")


def load_key():
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    key_file = PROJECT_ROOT / "api.key"
    if key_file.exists():
        return key_file.read_text().strip()
    sys.exit(f"Set GEMINI_API_KEY or create {key_file}")


def vocabulary():
    return [term.strip() for term in os.environ.get("WL_VOCAB", "").split(",") if term.strip()]


def open_source(config):
    """Open the audio source before connecting so device and file errors fail fast."""
    try:
        return WavFile(config.file) if config.file else Microphone(config.audio_device)
    except (OSError, EOFError, RuntimeError, ValueError) as e:
        sys.exit(f"Audio input error: {e}")


def describe(config):
    mode = ("Chinese interim + finalized translation" if config.show_zh
            else "Chinese preview -> English replacement")
    return (f"[Captions] {mode} | source={config.source_language} "
            f"| destination={config.destination_language}")


async def main(argv=None):
    config = parse_args(argv)
    client = genai.Client(api_key=load_key())
    source = open_source(config)
    print_logo()
    display = CaptionDisplay(config.zh_scale, config.en_scale, config.show_zh)
    coordinator = CaptionCoordinator(GeminiTranslator(client), display.handle, config.destination_language)
    transcriber = GeminiLiveTranscriber(client, config.language_codes, vocabulary())
    display.handle(SessionStatus(describe(config)))
    try:
        await transcriber.run(source, coordinator.handle)
        await coordinator.drain()
    except TimeoutError:
        sys.exit("Timed out waiting for the final transcription")
    finally:
        await coordinator.aclose()
        display.close()


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
