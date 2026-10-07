"""Caption IDs, translation task lifetime, and ordering metadata."""
import asyncio
import itertools
import time

from .events import FinalText, FinalTranscript, TranslationFailed, TranslationReady
from .translation import TranslationRequest

MAX_CONCURRENT_TRANSLATIONS = 4


class CaptionCoordinator:
    """Number finalized utterances and translate them concurrently.

    Caption IDs follow finalization order, so they stay stable when
    translations complete out of order. Call handle() from the event loop.
    """

    def __init__(self, translator, render, destination_language,
                 max_concurrent=MAX_CONCURRENT_TRANSLATIONS, clock=time.time):
        self._translator = translator
        self._render = render
        self._destination_language = destination_language
        self._clock = clock
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._ids = itertools.count(1)
        self._tasks = set()

    def handle(self, event):
        if not isinstance(event, FinalTranscript):
            self._render(event)
            return
        text = event.text.strip()
        if not text:
            return
        caption = FinalText(next(self._ids), text, self._clock())
        self._render(caption)
        task = asyncio.create_task(self._translate(caption))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _translate(self, caption):
        request = TranslationRequest(caption.text, self._destination_language)
        async with self._semaphore:
            try:
                translated = (await self._translator.translate(request)).strip()
            except Exception as e:
                self._render(TranslationFailed(caption.caption_id, str(e)))
                return
        if translated:
            self._render(TranslationReady(caption.caption_id, translated))
        else:
            self._render(TranslationFailed(caption.caption_id, "empty translation"))

    async def drain(self):
        """Wait for every pending translation, including ones started while waiting."""
        while self._tasks:
            await asyncio.gather(*self._tasks)

    async def aclose(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
