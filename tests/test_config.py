import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from caption_relay.config import DEFAULT_CONFIG, parse_args


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())

    def config(self, text):
        path = Path(self.directory) / "captions.toml"
        path.write_text(text)
        return str(path)

    def assertRejected(self, text, message):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            parse_args(["--config", self.config(text)])
        self.assertIn(message, stderr.getvalue())

    def test_project_defaults(self):
        args = parse_args([])
        self.assertEqual(args.config, str(DEFAULT_CONFIG))
        self.assertEqual(args.source_language, "auto")
        self.assertEqual(args.destination_language, "en")
        self.assertEqual(args.language_codes, [])
        self.assertEqual(args.audio_device, "pipewire")
        self.assertIsNone(args.file)

    def test_missing_sections_use_defaults(self):
        args = parse_args(["--config", self.config("")])
        self.assertEqual((args.zh_scale, args.en_scale, args.show_zh), (1.0, 1.0, True))
        self.assertEqual((args.source_language, args.destination_language), ("auto", "en"))
        self.assertEqual(args.audio_device, "pipewire")

    def test_cli_overrides_configuration(self):
        path = self.config('[display]\nzh_scale = 0.5\n[languages]\nsource = "en"\ndestination = "ja"\n')
        args = parse_args(["--config", path, "--zh-scale", "1.5",
                           "--source-language", "zh-TW", "--destination-language", "fr"])
        self.assertEqual(args.zh_scale, 1.5)
        self.assertEqual((args.source_language, args.destination_language), ("zh-TW", "fr"))

    def test_bcp47_source_becomes_single_language_hint(self):
        args = parse_args(["--config", self.config('[languages]\nsource = "zh-TW"\n')])
        self.assertEqual(args.language_codes, ["zh-TW"])

    def test_auto_source_is_case_insensitive(self):
        args = parse_args(["--config", self.config('[languages]\nsource = "AUTO"\n')])
        self.assertEqual(args.language_codes, [])

    def test_invalid_values_fail_with_actionable_messages(self):
        for text, message in (
                ("display = 1\n", "display must be a TOML table"),
                ("[display]\nzh_scale = 2.0\n", "display.zh_scale must be one of"),
                ("[display]\nen_scale = true\n", "display.en_scale must be one of"),
                ('[display]\nshow_zh = "no"\n', "display.show_zh must be true or false"),
                ('[languages]\nsource = " "\n', "languages.source must be auto"),
                ("[languages]\ndestination = 1\n", "languages.destination must be"),
                ('[audio]\ninput_device = ""\n', "audio.input_device must be"),
                ("[display\n", "Configuration")):
            with self.subTest(text=text):
                self.assertRejected(text, message)

    def test_missing_file_is_reported(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            parse_args(["--config", str(Path(self.directory) / "missing.toml")])
        self.assertIn("missing.toml", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
