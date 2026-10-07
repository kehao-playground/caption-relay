"""Per-utterance translation contract."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TranslationRequest:
    text: str
    destination_language: str


class Translator(Protocol):
    async def translate(self, request: TranslationRequest) -> str:
        """Return the destination-language text; raise on failure."""
        ...
