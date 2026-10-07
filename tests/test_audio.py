import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from caption_relay.audio import (CHUNK_BYTES, CHUNK_FRAMES, AudioChunk, Microphone, SilenceDetector,
                                 StreamEnd, UtteranceEnd, WavFile, audio_events)


def chunk(amplitude):
    return (np.full(CHUNK_FRAMES, amplitude * 32767, np.float32)).astype(np.int16).tobytes()


SPEECH, SILENCE = chunk(0.1), chunk(0.0)


class SilenceDetectorTests(unittest.TestCase):
    def test_silence_without_speech_never_ends_an_utterance(self):
        detector = SilenceDetector()
        self.assertFalse(any(detector.update(SILENCE) for _ in range(50)))

    def test_speech_then_six_silent_chunks_ends_once(self):
        detector = SilenceDetector()
        detector.update(SILENCE)  # Establish the noise floor.
        results = [detector.update(SPEECH) for _ in range(5)]
        results += [detector.update(SILENCE) for _ in range(20)]
        self.assertEqual(results.count(True), 1)
        self.assertTrue(results[5 + 5])

    def test_speech_resets_the_silence_count(self):
        detector = SilenceDetector()
        detector.update(SILENCE)
        detector.update(SPEECH)
        for _ in range(5):
            self.assertFalse(detector.update(SILENCE))
        self.assertFalse(detector.update(SPEECH))
        for _ in range(5):
            self.assertFalse(detector.update(SILENCE))
        self.assertTrue(detector.update(SILENCE))


class WavFileTests(unittest.TestCase):
    def write(self, rate=16000, channels=1, width=2, frames=CHUNK_FRAMES + 10):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        path = str(Path(directory) / "audio.wav")
        with wave.open(path, "wb") as w:
            w.setframerate(rate)
            w.setnchannels(channels)
            w.setsampwidth(width)
            w.writeframes(b"\1" * (frames * channels * width))
        return path

    def test_rejects_unsupported_format(self):
        for kwargs in ({"rate": 22050}, {"channels": 2}, {"width": 1}):
            with self.subTest(**kwargs), self.assertRaisesRegex(ValueError, "16 kHz mono 16-bit"):
                WavFile(self.write(**kwargs))

    def test_streams_fixed_size_chunks_and_pads_the_last_one(self):
        source = WavFile(self.write())
        with patch("caption_relay.audio.time.sleep"):
            chunks = list(source.chunks())
        source.close()
        self.assertEqual([len(c) for c in chunks], [CHUNK_BYTES, CHUNK_BYTES])
        self.assertEqual(chunks[1], b"\1" * 20 + b"\0" * (CHUNK_BYTES - 20))


class FakeSource:
    def __init__(self, chunks):
        self._chunks = chunks

    def chunks(self):
        yield from self._chunks

    def close(self):
        pass


class AudioEventTests(unittest.TestCase):
    def test_events_mark_pauses_and_the_explicit_end(self):
        events = list(audio_events(FakeSource([SILENCE, SPEECH] + [SILENCE] * 6 + [SPEECH])))
        kinds = [type(event) for event in events]
        self.assertEqual(kinds.count(AudioChunk), 9)
        self.assertEqual(kinds.count(UtteranceEnd), 1)
        self.assertEqual(kinds.index(UtteranceEnd), 8)  # Right after the sixth silent chunk.
        self.assertEqual(events[-1], StreamEnd())

    def test_empty_source_still_ends(self):
        self.assertEqual(list(audio_events(FakeSource([]))), [StreamEnd()])


class FakePyAudio:
    devices = [{"name": "PipeWire Sound Server Output", "maxInputChannels": 0},
               {"name": "HDA Intel PCH: ALC257 Analog (hw:0,0)", "maxInputChannels": 2},
               {"name": "pipewire", "maxInputChannels": 64}]
    open_error = None

    def __init__(self):
        FakePyAudio.instance = self
        self.terminated = False
        self.opened = None

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, index):
        return self.devices[index]

    def open(self, **kwargs):
        if self.open_error:
            raise self.open_error
        self.opened = kwargs
        return object()

    def terminate(self):
        self.terminated = True


class MicrophoneTests(unittest.TestCase):
    def setUp(self):
        FakePyAudio.open_error = None
        module = types.SimpleNamespace(PyAudio=FakePyAudio, paInt16=8)
        self.enterContext(patch.dict(sys.modules, {"pyaudio": module}))

    def test_selects_first_input_device_by_case_insensitive_fragment(self):
        Microphone("alc257")
        opened = FakePyAudio.instance.opened
        self.assertEqual(opened["input_device_index"], 1)
        self.assertEqual((opened["rate"], opened["channels"]), (16000, 1))

    def test_output_only_devices_are_not_selected(self):
        Microphone("PipeWire")
        self.assertEqual(FakePyAudio.instance.opened["input_device_index"], 2)

    def test_missing_device_is_reported_and_portaudio_released(self):
        with self.assertRaisesRegex(RuntimeError, "No input audio device matches 'USB Mic'"):
            Microphone("USB Mic")
        self.assertTrue(FakePyAudio.instance.terminated)

    def test_stream_open_failure_is_not_suppressed(self):
        FakePyAudio.open_error = OSError("Device unavailable")
        with self.assertRaisesRegex(OSError, "Device unavailable"):
            Microphone("pipewire")
        self.assertTrue(FakePyAudio.instance.terminated)


if __name__ == "__main__":
    unittest.main()
