"""Audio input: PortAudio microphone, WAV fixtures, and utterance-end detection."""
import collections
import contextlib
import ctypes
import time
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import numpy as np

SAMPLE_RATE = 16000
CHUNK_FRAMES = 1600  # 100 ms
CHUNK_BYTES = CHUNK_FRAMES * 2
MIME_TYPE = f"audio/pcm;rate={SAMPLE_RATE}"


@dataclass(frozen=True)
class AudioChunk:
    """100 ms of 16 kHz mono 16-bit PCM."""
    pcm: bytes


@dataclass(frozen=True)
class UtteranceEnd:
    """Speech was followed by sustained silence."""


@dataclass(frozen=True)
class StreamEnd:
    """The source has no more audio."""


AudioEvent = AudioChunk | UtteranceEnd | StreamEnd


class AudioSource(Protocol):
    def chunks(self) -> Iterator[bytes]: ...

    def close(self) -> None: ...


@contextlib.contextmanager
def _quiet_alsa():
    """Hide ALSA probe diagnostics while PortAudio enumerates devices."""
    try:
        asound = ctypes.CDLL("libasound.so.2")
    except OSError:  # No ALSA (for example macOS): nothing to suppress.
        yield
        return
    callback_type = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int,
                                     ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p)
    callback = callback_type(lambda *_: None)
    asound.snd_lib_error_set_handler(callback)
    try:
        yield
    finally:
        asound.snd_lib_error_set_handler(None)
        del callback


class Microphone:
    """PortAudio input stream selected by a case-insensitive device-name fragment."""

    def __init__(self, requested):
        import pyaudio
        with _quiet_alsa():
            self._pa = pyaudio.PyAudio()
            try:
                wanted = requested.lower()
                index = next((i for i in range(self._pa.get_device_count())
                              if self._pa.get_device_info_by_index(i).get("maxInputChannels", 0) > 0
                              and wanted in str(self._pa.get_device_info_by_index(i).get("name", "")).lower()),
                             None)
                if index is None:
                    raise RuntimeError(f"No input audio device matches {requested!r}")
                self._stream = self._pa.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
                                             input=True, input_device_index=index,
                                             frames_per_buffer=CHUNK_FRAMES)
            except Exception:
                self._pa.terminate()
                raise

    def chunks(self):
        while True:
            yield self._stream.read(CHUNK_FRAMES, exception_on_overflow=False)

    def close(self):
        self._stream.stop_stream()
        self._stream.close()
        self._pa.terminate()


class WavFile:
    """A 16 kHz mono 16-bit WAV file streamed in real time."""

    def __init__(self, path):
        self._wav = wave.open(path, "rb")
        if (self._wav.getframerate(), self._wav.getnchannels(), self._wav.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            self._wav.close()
            raise ValueError(f"{path}: audio file must be 16 kHz mono 16-bit PCM WAV")

    def chunks(self):
        while raw := self._wav.readframes(CHUNK_FRAMES):
            yield raw.ljust(CHUNK_BYTES, b"\0")
            time.sleep(CHUNK_FRAMES / SAMPLE_RATE)

    def close(self):
        self._wav.close()


class SilenceDetector:
    """Signal an utterance end after speech followed by sustained silence.

    The noise floor is the quietest chunk in a rolling window; a chunk is voiced
    when it is clearly above both that floor and an absolute minimum.
    """

    def __init__(self, silence_chunks=6, history=300, min_threshold=0.006, floor_ratio=2.5):
        self.silence_chunks = silence_chunks
        self.min_threshold = min_threshold
        self.floor_ratio = floor_ratio
        self._rms = collections.deque(maxlen=history)
        self._silence = 0
        self._had_speech = False

    def update(self, raw):
        """Return True when the chunk completes an utterance."""
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
        self._rms.append(rms)
        if rms > max(self.min_threshold, min(self._rms) * self.floor_ratio):
            self._silence, self._had_speech = 0, True
            return False
        self._silence += 1
        if self._had_speech and self._silence >= self.silence_chunks:
            self._silence, self._had_speech = 0, False
            return True
        return False


def audio_events(source, detector=None):
    """Yield the source's chunks, an UtteranceEnd after each detected pause, then StreamEnd."""
    detector = detector or SilenceDetector()
    for raw in source.chunks():
        yield AudioChunk(raw)
        if detector.update(raw):
            yield UtteranceEnd()
    yield StreamEnd()
