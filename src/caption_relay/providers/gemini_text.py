"""Gemini text translation for finalized utterances."""
import os

from google.genai import types

DEFAULT_MODEL = "gemini-flash-lite-latest"


def system_instruction(destination_language):
    return (f"Translate the transcript into concise, natural {destination_language} "
            "for live subtitles. Fix obvious transcription errors using context. "
            "Keep technical terms and model names as-is. Output ONLY the translation.")


class GeminiTranslator:
    def __init__(self, client, model=None):
        self._client = client
        self.model = model or os.environ.get("GEMINI_XLATE_MODEL", DEFAULT_MODEL)

    async def translate(self, request):
        response = await self._client.aio.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                system_instruction=system_instruction(request.destination_language),
                temperature=0.2, max_output_tokens=512),
            contents=request.text)
        return response.text or ""
