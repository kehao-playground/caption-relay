#!/usr/bin/env python3
"""Gemini Live 即時中→英字幕（最終版）

管線: 麥克風 → gemini-3.5-transcribe-live 串流逐字(中文, interim+final)
      → 每句 final 由 gemini-flash-latest 英譯

用法:
  captions_gemini.py                # 麥克風即時
  captions_gemini.py --file x.wav   # 檔案 1x 測試（16k mono wav）

金鑰: 環境變數 GEMINI_API_KEY，或本程式目錄的 api.key 檔案
術語: 環境變數 WL_VOCAB="Whisper,CPU,Kubernetes"（可選，最多少量提升辨識）
"""
import argparse, asyncio, ctypes, os, sys, threading, time, tomllib, wave

from google import genai
from google.genai import types

from caption_display import CaptionDisplay

BASE = os.path.dirname(os.path.abspath(__file__))
SR = 16000
CHUNK = 1600  # 100ms
CAPTION_SCALES = (0.5, 1.0, 1.2, 1.5)
LANGUAGE_AUTO = "auto"
DEFAULT_SOURCE_LANGUAGE = "auto"
DEFAULT_DESTINATION_LANGUAGE = "en"

LOGO = r"""
  ____                           _       ____            _       _
 / ___|__ _ _ __  _ __   __ _  | |_ ___/ ___|__ _ _ __ | |_   _| |_ ___  ___
| |   / _` | '_ \| '_ \ / _` | | __/ _ \ |   / _` | '_ \| | | | | __/ _ \/ __|
| |__| (_| | |_) | |_) | (_| | | ||  __/ |__| (_| | |_) | | |_| | ||  __/\__ \
 \____\__,_| .__/| .__/ \__,_|  \__\___|\____\__,_| .__/|_|\__,_|\__\___||___/
           |_|   |_|                               |_|
"""


def _open_microphone(requested):
    import pyaudio
    asound = ctypes.CDLL("libasound.so.2")
    callback_type = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int,
                                     ctypes.c_char_p, ctypes.c_int,
                                     ctypes.c_char_p)
    callback = callback_type(lambda *_: None)
    asound.snd_lib_error_set_handler(callback)
    pa = pyaudio.PyAudio()
    try:
        wanted = requested.lower()
        index = next((i for i in range(pa.get_device_count())
                      if pa.get_device_info_by_index(i).get("maxInputChannels", 0) > 0
                      and wanted in str(pa.get_device_info_by_index(i).get("name", "")).lower()), None)
        if index is None:
            raise RuntimeError(f"No input audio device matches {requested!r}")
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=SR,
                         input=True, input_device_index=index,
                         frames_per_buffer=CHUNK)
        return pa, stream
    except Exception:
        pa.terminate()
        raise
    finally:
        asound.snd_lib_error_set_handler(None)
        del callback


def print_logo():
    if sys.stdout.isatty():
        print(LOGO, end="")


def load_key():
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    kf = os.path.join(BASE, "api.key")
    if os.path.exists(kf):
        return open(kf).read().strip()
    sys.exit(f"Set GEMINI_API_KEY or create {kf}")


async def translate(client, text, sem, display, caption_id, destination_language):
    async with sem:
        try:
            r = await client.aio.models.generate_content(
                model=os.environ.get("GEMINI_XLATE_MODEL", "gemini-flash-lite-latest"),
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
def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--config", default=os.path.join(BASE, "captions.toml"),
                    help="Configuration file (default: project captions.toml)")
    ap.add_argument("--zh-scale", type=float, choices=CAPTION_SCALES,
                    help="Override Chinese caption scale")
    ap.add_argument("--en-scale", type=float, choices=CAPTION_SCALES,
                    help="Override destination caption scale")
    ap.add_argument("--source-language", help="Override source language (auto or BCP-47 code)")
    ap.add_argument("--destination-language", help="Override destination language (BCP-47 code or name)")
    args = ap.parse_args(argv)
    try:
        with open(args.config, "rb") as config_file:
            config = tomllib.load(config_file)
        display = config.get("display", {})
        languages = config.get("languages", {})
        audio = config.get("audio", {})
        if not all(isinstance(value, dict) for value in (display, languages, audio)):
            raise ValueError("display, languages, and audio must be TOML tables")
        for name, default in (("zh_scale", 1.0), ("en_scale", 1.0)):
            value = display.get(name, default)
            if isinstance(value, bool) or value not in CAPTION_SCALES:
                raise ValueError(f"display.{name} must be one of {CAPTION_SCALES}")
            if getattr(args, name) is None:
                setattr(args, name, value)
        args.show_zh = display.get("show_zh", True)
        if not isinstance(args.show_zh, bool):
            raise ValueError("display.show_zh must be true or false")
        args.source_language = args.source_language or languages.get("source", DEFAULT_SOURCE_LANGUAGE)
        args.destination_language = args.destination_language or languages.get("destination", DEFAULT_DESTINATION_LANGUAGE)
        if not isinstance(args.source_language, str) or not args.source_language.strip():
            raise ValueError("languages.source must be auto or a BCP-47 code")
        if not isinstance(args.destination_language, str) or not args.destination_language.strip():
            raise ValueError("languages.destination must be a BCP-47 code or name")
        args.audio_device = audio.get("input_device", "pipewire")
        if not isinstance(args.audio_device, str) or not args.audio_device.strip():
            raise ValueError("audio.input_device must be a device name fragment")
    except (OSError, ValueError, tomllib.TOMLDecodeError) as e:
        ap.error(f"Configuration {args.config}: {e}")
    return args


async def main():
    args = parse_args()
    print_logo()

    client = genai.Client(api_key=load_key())
    vocab = [t.strip() for t in os.environ.get("WL_VOCAB", "").split(",") if t.strip()]
    cfg = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        input_audio_transcription=types.AudioTranscriptionConfig(
            language_codes=[] if args.source_language.lower() == LANGUAGE_AUTO else [args.source_language],
            mode="SMART",
            custom_vocabulary=vocab or None,
        ),
    )
    model = os.environ.get("GEMINI_LIVE_MODEL", "gemini-3.5-transcribe-live")
    print(f"[Connecting] {model}", flush=True)
    async with client.aio.live.connect(model=model, config=cfg) as session:
        display_mode = "Chinese interim + finalized translation" if args.show_zh else "Chinese preview -> English replacement"
        print(f"[Captions started] {display_mode} | source={args.source_language} | destination={args.destination_language} | Ctrl-C to stop", flush=True)
        sem = asyncio.Semaphore(4)
        display = CaptionDisplay(args.zh_scale, args.en_scale, args.show_zh)

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
                    task = asyncio.create_task(translate(client, text, sem, display, caption_id, args.destination_language))
                    translations.add(task)
                    task.add_done_callback(translations.discard)
                    final_received.set()

        recv = asyncio.create_task(receiver())
        loop = asyncio.get_running_loop()

        def sender(chunk):
            asyncio.run_coroutine_threadsafe(
                session.send_realtime_input(audio=types.Blob(
                    data=chunk, mime_type="audio/pcm;rate=16000")), loop)

        def capture():
            import collections
            import numpy as np
            sil, had_speech = 0, False
            floor_est = [0.005]
            rms_hist = collections.deque(maxlen=300)

            def send_chunk(raw):
                nonlocal sil, had_speech
                sender(raw)
                x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(x * x)))
                rms_hist.append(rms)
                floor_est[0] = min(rms_hist)
                voiced = rms > max(0.006, floor_est[0] * 2.5)
                if voiced:
                    sil, had_speech = 0, True
                else:
                    sil += 1
                if had_speech and sil >= 6:
                    asyncio.run_coroutine_threadsafe(
                        session.send_realtime_input(audio_stream_end=True), loop).result(timeout=10)
                    had_speech, sil = False, 0

            if args.file:
                wf = wave.open(args.file, "rb")
                if wf.getframerate() != SR or wf.getnchannels() != 1:
                    raise ValueError("Audio file must be 16 kHz mono WAV")
                while True:
                    raw = wf.readframes(CHUNK)
                    if not raw:
                        break
                    if len(raw) < CHUNK * 2:
                        raw = raw.ljust(CHUNK * 2, b"\0")
                    send_chunk(raw)
                    time.sleep(0.1)
            else:
                pa, st = _open_microphone(args.audio_device)
                try:
                    while True:
                        send_chunk(st.read(CHUNK, exception_on_overflow=False))
                except KeyboardInterrupt:
                    pass
                finally:
                    st.stop_stream(); st.close(); pa.terminate()
            async def finish_audio():
                final_received.clear()
                await session.send_realtime_input(audio_stream_end=True)
            asyncio.run_coroutine_threadsafe(finish_audio(), loop).result(timeout=10)

        cap = threading.Thread(target=capture, daemon=True)
        cap.start()
        try:
            if args.file:
                await asyncio.to_thread(cap.join)
                await asyncio.wait_for(final_received.wait(), timeout=20)
                if translations:
                    await asyncio.gather(*translations)
            else:
                await recv
        finally:
            recv.cancel()
            await asyncio.gather(recv, return_exceptions=True)
            display.close()



if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
