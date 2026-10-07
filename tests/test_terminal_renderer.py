import contextlib
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from caption_relay.events import (FinalText, InterimText, SessionStatus, TranslationFailed,
                                  TranslationReady)
from caption_relay.renderers.terminal import CaptionDisplay, print_caption


KITTY_PARSE = """
import json, sys
from kitty.fast_data_types import Screen
screen = Screen(None, int(sys.argv[1]), int(sys.argv[2]), 100, 10, 20)
data = memoryview(sys.stdin.buffer.read())
while data:
    buffer = screen.test_create_write_buffer()
    consumed = screen.test_commit_write_buffer(data, buffer)
    data = data[consumed:]
    screen.test_parse_written_data(None)
print(json.dumps({"lines": [str(screen.line(row)) for row in range(screen.lines)],
                  "cursor": [screen.cursor.x, screen.cursor.y]}, ensure_ascii=False))
"""


class EventDriver:
    """Feed CaptionDisplay synthetic events the way CaptionCoordinator does."""

    def __init__(self, *args):
        self.display = CaptionDisplay(*args)
        self.ids = itertools.count(1)

    def interim(self, text):
        self.display.handle(InterimText(text))

    def final(self, text):
        caption_id = next(self.ids)
        self.display.handle(FinalText(caption_id, text, 0.0))
        return caption_id

    def translated(self, caption_id, text):
        self.display.handle(TranslationReady(next(self.ids) if caption_id is None else caption_id, text))

    def failed(self, caption_id, error):
        self.display.handle(TranslationFailed(caption_id, error))

    def status(self, message):
        self.display.handle(SessionStatus(message))

    def close(self):
        self.display.close()


class Terminal(io.StringIO):
    def isatty(self):
        return True


@unittest.skipUnless(shutil.which("kitty"), "Kitty is required for terminal integration tests")
class CaptionDisplayTests(unittest.TestCase):
    def setUp(self):
        self.output = Terminal()
        self.enterContext(contextlib.redirect_stdout(self.output))
        self.enterContext(patch.dict(os.environ, {"KITTY_WINDOW_ID": "test", "COLUMNS": "40"}))

    def rendered(self, rows=24, columns=40):
        # A normal TTY converts LF to CRLF before Kitty parses the output.
        output = self.output.getvalue().replace("\n", "\r\n").encode()
        result = subprocess.run(["kitty", "+runpy", KITTY_PARSE, str(rows), str(columns)],
                                input=output, capture_output=True, check=True)
        return json.loads(result.stdout)

    def screen(self, rows=24, columns=40):
        return "\n".join(self.rendered(rows, columns)["lines"])

    def test_chinese_preview_is_replaced_by_scaled_english(self):
        display = EventDriver(0.5, 1.2, False)
        display.interim("中文辨識進度")
        self.assertIn("中文辨識進度", self.screen())
        caption_id = display.final("中文定稿")
        self.assertIn("中文定稿", self.screen())
        display.translated(caption_id, "Complete")
        screen = self.screen()
        self.assertIn("Complete", screen)
        self.assertNotIn("中文", screen)

    def test_previous_translation_preserves_newer_interim(self):
        display = EventDriver(1.0, 1.2, False)
        first = display.final("第一句中文")
        display.interim("第二句辨識中")
        display.translated(first, "First")
        screen = self.screen()
        self.assertIn("First", screen)
        self.assertIn("第二句辨識中", screen)
        self.assertNotIn("第一句中文", screen)
        self.assertLess(screen.index("First"), screen.index("第二句辨識中"))

    def test_old_translation_preserves_newer_final_until_it_is_translated(self):
        display = EventDriver(1.0, 1.2, False)
        first = display.final("第一句中文")
        second = display.final("第二句中文")
        display.translated(first, "First")
        self.assertIn("第二句中文", self.screen())
        display.translated(second, "Second")
        screen = self.screen()
        self.assertIn("First", screen)
        self.assertIn("Second", screen)
        self.assertNotIn("中文", screen)

    def test_out_of_order_completion_keeps_both_english_captions(self):
        display = EventDriver(1.0, 1.2, False)
        first = display.final("第一句中文")
        second = display.final("第二句中文")
        display.translated(second, "Second")
        display.translated(first, "First")
        screen = self.screen()
        self.assertIn("Second", screen)
        self.assertIn("First", screen)
        self.assertNotIn("中文", screen)

    def test_long_preview_does_not_leave_wrapped_chinese_behind(self):
        display = EventDriver(1.0, 1.2, False)
        display.interim("很長的中文辨識進度" * 20)
        caption_id = display.final("很長的中文定稿" * 20)
        display.translated(caption_id, "Complete")
        screen = self.screen()
        self.assertIn("Complete", screen)
        self.assertNotIn("中文", screen)
        self.assertNotIn("…", screen)

    def test_two_row_preview_at_bottom_is_fully_replaced(self):
        display = EventDriver(1.5, 1.2, False)
        print("\n" * 11, end="")
        caption_id = display.final("中文定稿")
        self.assertIn("中文定稿", self.screen(rows=12))
        display.translated(caption_id, "Complete")
        screen = self.screen(rows=12)
        self.assertIn("Complete", screen)
        self.assertNotIn("中文", screen)

    def test_translation_failure_preserves_chinese_until_success(self):
        display = EventDriver(1.0, 1.2, False)
        caption_id = display.final("中文定稿")
        display.failed(caption_id, "translation failed")
        screen = self.screen()
        self.assertIn("Translation failed", screen)
        self.assertIn("中文定稿", screen)
        display.translated(caption_id, "Complete")
        screen = self.screen()
        self.assertIn("Translation failed", screen)
        self.assertIn("Complete", screen)
        self.assertNotIn("中文", screen)

    def test_scaled_caption_has_no_per_character_or_chunk_boundary_padding(self):
        for scale, text, width in ((1.2, "abcdefghij" * 2, 24),
                                   (1.5, "abcdefgh" * 2, 24),
                                   (1.2, "café—test!" * 2, 24)):
            with self.subTest(scale=scale, text=text):
                self.output.seek(0)
                self.output.truncate()
                print_caption(text, "", scale, newline=False)
                rendered = self.rendered()
                self.assertEqual(rendered["lines"][0], text)
                self.assertEqual(rendered["cursor"], [width, 0])

    def test_wrapped_scaled_caption_preserves_text_and_following_caption(self):
        display = EventDriver(1.0, 1.2, False)
        text = "abcdefghij" * 7
        display.translated(None, text)
        display.translated(None, "Following caption")
        screen = self.screen()
        content = "".join(line for line in screen.split("\n") if not line.startswith("─"))
        self.assertIn(text, content)
        self.assertIn("Following caption", screen)
        self.assertLess(screen.index("abcdefghij"), screen.index("Following caption"))

    def test_long_scaled_preview_leaves_no_chinese_after_replacement(self):
        display = EventDriver(1.5, 1.2, False)
        caption_id = display.final("很長的中文定稿" * 20)
        display.translated(caption_id, "Complete")
        screen = self.screen()
        self.assertIn("Complete", screen)
        self.assertNotIn("中文", screen)
        self.assertNotIn("…", screen)

    def test_narrow_scaled_caption_keeps_every_character(self):
        with patch.dict(os.environ, {"COLUMNS": "10"}):
            print_caption("abcdefghij" * 3, "", 1.2)
        screen = self.screen(rows=24, columns=10)
        self.assertEqual(screen.replace("\n", ""), "abcdefghij" * 3)

    def test_mixed_width_scaled_preview_stays_on_one_caption_line(self):
        for scale in (1.2, 1.5):
            with self.subTest(scale=scale):
                self.output.seek(0)
                self.output.truncate()
                display = EventDriver(scale, 1.2, False)
                caption_id = display.final("ab中cd文" * 20)
                lines = self.rendered()["lines"]
                self.assertTrue(lines[0].startswith("ZH  "))
                self.assertEqual("".join(lines[1:]), "")
                display.translated(caption_id, "Complete")
                screen = self.screen()
                self.assertIn("Complete", screen)
                self.assertNotIn("中", screen)
                self.assertNotIn("文", screen)
                self.assertNotIn("…", screen)

    def test_show_chinese_mode_keeps_both_final_languages(self):
        display = EventDriver(0.5, 1.2, True)
        display.interim("中文草稿")
        caption_id = display.final("中文定稿")
        display.translated(caption_id, "Complete")
        screen = self.screen()
        self.assertIn("中文定稿", screen)
        self.assertIn("Complete", screen)
        self.assertNotIn("中文草稿", screen)

    def test_redirected_output_keeps_only_english_without_cursor_controls(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            display = EventDriver(1.0, 1.2, False)
            display.interim("中文草稿")
            caption_id = display.final("中文定稿")
            display.translated(caption_id, "Complete")
            display.close()
        self.assertEqual(output.getvalue(), "Complete\n")
        self.assertNotIn("中文", output.getvalue())
        self.assertNotIn("\033", output.getvalue())

    def test_separator_divides_completed_captions_without_erasing_new_preview(self):
        display = EventDriver(1.0, 1.0, False)
        first = display.final("第一句中文")
        display.translated(first, "First caption")
        self.assertNotIn("─", self.screen())
        second = display.final("第二句中文")
        display.interim("第三句辨識進度")
        display.translated(second, "Second caption")
        lines = self.rendered()["lines"]
        self.assertEqual(lines[:4], ["First caption", "─" * 39, "Second caption", "… 第三句辨識進度"])

    def test_wrapped_sentence_gets_only_one_separator_before_next_sentence(self):
        display = EventDriver(1.0, 1.0, False)
        display.translated(None, "a" * 60)
        display.translated(None, "Next sentence")
        lines = self.rendered()["lines"]
        self.assertEqual(lines[:4], ["a" * 40, "a" * 20, "─" * 39, "Next sentence"])

    def test_redirected_caption_history_has_no_visual_separators(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            display = EventDriver(1.0, 1.0, False)
            display.translated(None, "First caption")
            display.translated(None, "Second caption")
        self.assertEqual(output.getvalue(), "First caption\nSecond caption\n")

    def test_status_message_keeps_the_current_preview(self):
        display = EventDriver(1.0, 1.0, False)
        display.interim("中文辨識進度")
        display.status("[Connected] Ctrl-C to stop")
        lines = self.rendered()["lines"]
        self.assertEqual(lines[:2], ["[Connected] Ctrl-C to stop", "… 中文辨識進度"])

    def test_unknown_event_is_rejected(self):
        with self.assertRaises(TypeError):
            CaptionDisplay(1.0, 1.0, False).handle("text")


class ImportBoundaryTests(unittest.TestCase):
    def test_renderer_and_coordinator_do_not_import_the_google_sdk(self):
        code = ("import sys, caption_relay.renderers.terminal, caption_relay.coordinator; "
                "sys.exit(any(name.split('.')[0] == 'google' for name in sys.modules))")
        subprocess.run([sys.executable, "-c", code], check=True)


if __name__ == "__main__":
    unittest.main()
