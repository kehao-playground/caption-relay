"""Gemini Live transcription session and per-utterance Gemini text translation."""
import asyncio
import contextlib
import os
import threading

from google.genai import types

from ..audio import MIME_TYPE, AudioChunk, UtteranceEnd, audio_events

DEFAULT_LIVE_MODEL = "gemini-3.5-transcribe-live"
DEFAULT_TRANSLATION_MODEL = "gemini-flash-lite-latest"
MAX_CONCURRENT_TRANSLATIONS = 4
FINAL_TRANSCRIPT_TIMEOUT = 20  # seconds to wait for the last finalized text of a file
SEND_TIMEOUT = 10


def live_model():
    return os.environ.get("GEMINI_LIVE_MODEL", DEFAULT_LIVE_MODEL)


def live_config(language_codes, vocabulary):
    return types.LiveConnectConfig(
        response_modalities=["TEXT"],
        input_audio_transcription=types.AudioTranscriptionConfig(
            language_codes=language_codes,
            mode="SMART",
            custom_vocabulary=vocabulary or None,
        ),
    )


async def translate(client, text, sem, display, caption_id, destination_language):
    async with sem:
        try:
            r = await client.aio.models.generate_content(
                model=os.environ.get("GEMINI_XLATE_MODEL", DEFAULT_TRANSLATION_MODEL),
                config=types.GenerateContentConfig(
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    system_instruction=(
                        f"Translate the transcript into concise, natural {destination_language} "
                        "for live subtitles. Fix obvious transcription errors using context. "
                        "Keep technical terms and model names as-is. Output ONLY the translation."),
                    temperature=0.2, max_output_tokens=512),
                contents=text)
            translated = (r.text or "").strip()
            if translated:
                display.translated(caption_id, translated)
        except Exception as e:
            display.failed(e)


def _start_capture(source, session, loop):
    """Stream source chunks from a daemon thread; the future reports completion or failure.

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


async def run_session(client, config, source, display, vocabulary):
    """Run one Gemini Live session until the source ends (file) or the user stops it."""
    async with client.aio.live.connect(model=live_model(),
                                       config=live_config(config.language_codes, vocabulary)) as session:
        mode = ("Chinese interim + finalized translation" if config.show_zh
                else "Chinese preview -> English replacement")
        print(f"[Captions started] {mode} | source={config.source_language} "
              f"| destination={config.destination_language} | Ctrl-C to stop", flush=True)
        sem = asyncio.Semaphore(MAX_CONCURRENT_TRANSLATIONS)
        translations = set()
        final_received = asyncio.Event()

        async def receiver():
            async for resp in session.receive():
                sc = resp.server_content
                if not sc:
                    continue
                it = sc.interim_input_transcription
                if it and it.text:
                    final_received.clear()
                    display.interim(it.text)
                ft = sc.input_transcription
                if ft and ft.text:
                    text = ft.text.strip()
                    caption_id = display.final(text)
                    task = asyncio.create_task(
                        translate(client, text, sem, display, caption_id, config.destination_language))
                    translations.add(task)
                    task.add_done_callback(translations.discard)
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
            # The source ended: flush the last utterance and wait for its translation.
            final_received.clear()
            await asyncio.wait_for(session.send_realtime_input(audio_stream_end=True), SEND_TIMEOUT)
            await asyncio.wait_for(final_received.wait(), FINAL_TRANSCRIPT_TIMEOUT)
            if translations:
                await asyncio.gather(*translations)
        finally:
            recv.cancel()
            await asyncio.gather(recv, return_exceptions=True)
