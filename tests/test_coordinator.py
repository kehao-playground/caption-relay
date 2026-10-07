import asyncio
import unittest

from caption_relay.coordinator import CaptionCoordinator
from caption_relay.events import (FinalText, FinalTranscript, InterimText, SessionStatus,
                                  TranslationFailed, TranslationReady)
from caption_relay.translation import TranslationRequest


class FakeTranslator:
    """Translate to upper case once the test releases that source text."""

    def __init__(self, gated=(), errors=None):
        self.gates = {text: asyncio.Event() for text in gated}
        self.errors = errors or {}
        self.requests = []
        self.active = 0
        self.max_active = 0

    async def translate(self, request):
        self.requests.append(request)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if request.text in self.gates:
                await self.gates[request.text].wait()
            else:
                await asyncio.sleep(0)
            if request.text in self.errors:
                raise self.errors[request.text]
            return "" if request.text == "silent" else f" {request.text.upper()} "
        finally:
            self.active -= 1


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def coordinator(self, translator, **kwargs):
        self.events = []
        return CaptionCoordinator(translator, self.events.append, "ja", clock=lambda: 42.0, **kwargs)

    async def test_finals_get_sequential_ids_and_receive_time(self):
        coordinator = self.coordinator(FakeTranslator())
        coordinator.handle(FinalTranscript(" one "))
        coordinator.handle(FinalTranscript("two"))
        await coordinator.drain()
        self.assertEqual(self.events[:2], [FinalText(1, "one", 42.0), FinalText(2, "two", 42.0)])
        self.assertCountEqual(self.events[2:], [TranslationReady(1, "ONE"), TranslationReady(2, "TWO")])

    async def test_out_of_order_completion_keeps_caption_ids(self):
        translator = FakeTranslator(gated=("first", "second"))
        coordinator = self.coordinator(translator)
        coordinator.handle(FinalTranscript("first"))
        coordinator.handle(FinalTranscript("second"))
        await asyncio.sleep(0)
        translator.gates["second"].set()
        await asyncio.sleep(0.01)
        translator.gates["first"].set()
        await coordinator.drain()
        self.assertEqual(self.events[2:], [TranslationReady(2, "SECOND"), TranslationReady(1, "FIRST")])

    async def test_request_carries_destination_language(self):
        translator = FakeTranslator()
        coordinator = self.coordinator(translator)
        coordinator.handle(FinalTranscript("text"))
        await coordinator.drain()
        self.assertEqual(translator.requests, [TranslationRequest("text", "ja")])

    async def test_failures_and_empty_translations_are_reported_per_caption(self):
        coordinator = self.coordinator(FakeTranslator(errors={"bad": RuntimeError("quota exceeded")}))
        coordinator.handle(FinalTranscript("bad"))
        coordinator.handle(FinalTranscript("silent"))
        await coordinator.drain()
        self.assertCountEqual(self.events[2:], [TranslationFailed(1, "quota exceeded"),
                                                TranslationFailed(2, "empty translation")])

    async def test_blank_final_is_ignored_and_other_events_pass_through(self):
        coordinator = self.coordinator(FakeTranslator())
        coordinator.handle(SessionStatus("[Connected]"))
        coordinator.handle(InterimText("partial"))
        coordinator.handle(FinalTranscript("   "))
        await coordinator.drain()
        self.assertEqual(self.events, [SessionStatus("[Connected]"), InterimText("partial")])

    async def test_concurrency_is_bounded(self):
        translator = FakeTranslator(gated=("a", "b", "c", "d"))
        coordinator = self.coordinator(translator, max_concurrent=2)
        for text in "abcd":
            coordinator.handle(FinalTranscript(text))
        await asyncio.sleep(0.01)
        self.assertEqual(translator.active, 2)
        for gate in translator.gates.values():
            gate.set()
        await coordinator.drain()
        self.assertEqual(translator.max_active, 2)
        self.assertEqual(len(self.events), 8)

    async def test_aclose_cancels_pending_translations(self):
        coordinator = self.coordinator(FakeTranslator(gated=("never",)))
        coordinator.handle(FinalTranscript("never"))
        await asyncio.sleep(0)
        await asyncio.wait_for(coordinator.aclose(), 1)
        self.assertEqual(self.events, [FinalText(1, "never", 42.0)])


if __name__ == "__main__":
    unittest.main()
