import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from caption_relay.audio import CHUNK_BYTES, CHUNK_FRAMES, SilenceDetector, WavFile


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


if __name__ == "__main__":
    unittest.main()
