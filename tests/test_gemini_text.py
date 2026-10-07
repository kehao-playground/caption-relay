import types
import unittest

from caption_relay.providers.gemini_text import GeminiTranslator
from caption_relay.translation import TranslationRequest


class FakeModels:
    def __init__(self, text):
        self.text = text
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(text=self.text)


class GeminiTranslatorTests(unittest.IsolatedAsyncioTestCase):
    def translator(self, text):
        self.models = FakeModels(text)
        client = types.SimpleNamespace(aio=types.SimpleNamespace(models=self.models))
        return GeminiTranslator(client, model="test-model")

    async def test_request_uses_destination_language_and_disables_function_calling(self):
        result = await self.translator("Bonjour").translate(TranslationRequest("你好", "fr"))
        self.assertEqual(result, "Bonjour")
        call, = self.models.calls
        self.assertEqual((call["model"], call["contents"]), ("test-model", "你好"))
        self.assertIn("natural fr ", call["config"].system_instruction)
        self.assertTrue(call["config"].automatic_function_calling.disable)

    async def test_missing_text_becomes_empty_string(self):
        self.assertEqual(await self.translator(None).translate(TranslationRequest("你好", "en")), "")


if __name__ == "__main__":
    unittest.main()
