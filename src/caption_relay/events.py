"""Events exchanged between transcription providers, the coordinator, and renderers.

Providers emit SessionStatus, InterimText, and FinalTranscript. The coordinator
turns each FinalTranscript into a FinalText with a caption ID and later emits
TranslationReady or TranslationFailed for that ID. Renderers consume everything
except FinalTranscript and never see provider response models.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionStatus:
    message: str


@dataclass(frozen=True)
class InterimText:
    text: str


@dataclass(frozen=True)
class FinalTranscript:
    """Finalized source text from a provider, before it has a caption ID."""
    text: str


@dataclass(frozen=True)
class FinalText:
    caption_id: int
    text: str
    received_at: float  # Application receive time (epoch seconds), not a word timestamp.


@dataclass(frozen=True)
class TranslationReady:
    caption_id: int
    text: str


@dataclass(frozen=True)
class TranslationFailed:
    caption_id: int
    error: str


TranscriptionEvent = SessionStatus | InterimText | FinalTranscript
CaptionEvent = SessionStatus | InterimText | FinalText | TranslationReady | TranslationFailed
