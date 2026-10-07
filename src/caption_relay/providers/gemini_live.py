"""Gemini Live transcription provider."""
import asyncio
import contextlib
import os
import threading

from google.genai import types

from ..audio import MIME_TYPE, AudioChunk, UtteranceEnd, audio_events
from ..events import FinalTranscript, InterimText, SessionStatus

DEFAULT_MODEL = "gemini-3.5-transcribe-live"
FINAL_TRANSCRIPT_TIMEOUT = 20  # seconds to wait for the last finalized text of a file
SEND_TIMEOUT = 10


def live_config(language_codes, vocabulary):
    return types.LiveConnectConfig(
        response_modalities=["TEXT"],
        input_audio_transcription=types.AudioTranscriptionConfig(
            language_codes=language_codes,
            mode="SMART",
            custom_vocabulary=vocabulary or None,
        ),
    )


def _start_capture(source, session, loop):
    """Stream audio events from a daemon thread; the future reports completion or failure.

    A daemon thread (not asyncio.to_thread) keeps a blocking microphone read from
    delaying interpreter exit after Ctrl-C.
    """
    done = loop.create_future()

    def send(**kwargs):
        return asyncio.run_coroutine_threadsafe(session.send_realtime_input(**kwargs), loop)

    def capture():
        try:
            for event in audio_events(source):
                if isinstance(event, AudioChunk):
                    send(audio=types.Blob(data=event.pcm, mime_type=MIME_TYPE))
                elif isinstance(event, UtteranceEnd):
                    send(audio_stream_end=True).result(timeout=SEND_TIMEOUT)
            result = None, None
        except BaseException as e:
            result = None, e
        finally:
            source.close()
        with contextlib.suppress(RuntimeError):  # The loop already closed after Ctrl-C.
            loop.call_soon_threadsafe(_settle, done, *result)

    threading.Thread(target=capture, daemon=True).start()
    return done


def _settle(future, result, error):
    if future.done():
        return
    if error is None:
        future.set_result(result)
    else:
        future.set_exception(error)


class GeminiLiveTranscriber:
    def __init__(self, client, language_codes, vocabulary, model=None):
        self._client = client
        self._config = live_config(language_codes, vocabulary)
        self.model = model or os.environ.get("GEMINI_LIVE_MODEL", DEFAULT_MODEL)

    async def run(self, source, emit):
        """Transcribe source until it ends (file) or the user stops it, emitting events."""
        emit(SessionStatus(f"[Connecting] {self.model}"))
        async with self._client.aio.live.connect(model=self.model, config=self._config) as session:
            emit(SessionStatus("[Connected] Ctrl-C to stop"))
            final_received = asyncio.Event()

            async def receiver():
                async for response in session.receive():
                    content = response.server_content
                    if not content:
                        continue
                    interim = content.interim_input_transcription
                    if interim and interim.text:
                        final_received.clear()
                        emit(InterimText(interim.text))
                    final = content.input_transcription
                    if final and final.text:
                        emit(FinalTranscript(final.text))
                        final_received.set()

            recv = asyncio.create_task(receiver())
            capture = _start_capture(source, session, asyncio.get_running_loop())
            try:
                # Surface a receiver or capture failure instead of waiting forever.
                await asyncio.wait({recv, capture}, return_when=asyncio.FIRST_COMPLETED)
                if recv.done():
                    recv.result()
                    return
                capture.result()
                # The source ended: flush the last utterance and wait for its final text.
                final_received.clear()
                await asyncio.wait_for(session.send_realtime_input(audio_stream_end=True), SEND_TIMEOUT)
                await asyncio.wait_for(final_received.wait(), FINAL_TRANSCRIPT_TIMEOUT)
            finally:
                recv.cancel()
                await asyncio.gather(recv, return_exceptions=True)
