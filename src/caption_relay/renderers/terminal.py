"""Terminal caption history and temporary Chinese previews."""
import math
import os
import shutil
import sys
import time
import unicodedata

from ..events import FinalText, InterimText, SessionStatus, TranslationFailed, TranslationReady

GUTTER_STYLE = "\033[2;90m"

SCALED_LAYOUT = {
    0.5: (1, 1, 2),
    1.2: (2, 3, 5),
    1.5: (2, 3, 4),
}


def _cell_width(character):
    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in "WF" else 1


def _clean_line(line):
    return "".join(character if ord(character) >= 32 and not 127 <= ord(character) <= 159 else " "
                   for character in line)


def _scaled_chunks(line, scale, columns):
    rows, numerator, denominator = SCALED_LAYOUT[scale]
    quantum = denominator // math.gcd(numerator, denominator)
    # 整數寬度區塊避免分段留白；窄分割時縮短區塊，不能超出螢幕。
    max_cells = min(7, columns // rows) * denominator // numerator
    limit = max(1, max_cells // quantum * quantum or max_cells)
    chunk = []
    cells = 0
    for character in line:
        width = _cell_width(character)
        candidate = cells + width
        if chunk and candidate > limit:
            yield "".join(chunk), cells
            chunk, cells = [], 0
        chunk.append(character)
        cells += width
    if chunk:
        yield "".join(chunk), cells


def _wrap_cells(line, width):
    """Split a line into segments of at most width terminal cells."""
    segment, cells = [], 0
    for character in line:
        cell_width = _cell_width(character)
        if segment and cells + cell_width > width:
            yield "".join(segment)
            segment, cells = [], 0
        segment.append(character)
        cells += cell_width
    yield "".join(segment)


def _render_scaled_line(line, scale, columns, indent=0):
    rows, numerator, denominator = SCALED_LAYOUT[scale]
    used = 0
    output = []
    for chunk, cells in _scaled_chunks(line, scale, columns):
        width = max(1, (numerator * cells + denominator - 1) // denominator)
        block_width = rows * width
        if used and used + block_width > columns:
            output.append("\n" * rows + " " * indent)
            used = 0
        metadata = f"s={rows}:n={numerator}:d={denominator}:v=2:w={width}"
        output.append(f"\033]66;{metadata};{chunk}\a")
        used += block_width
    return "".join(output)


def print_caption(text, style, scale, *, newline=True, gutter=""):
    """只縮放字幕文字，不改 Kitty 視窗的基礎字級。

    gutter is unscaled metadata in a left column; wrapped rows are indented
    by its width so the metadata appears once per caption.
    """
    terminal = sys.stdout.isatty()
    scaled = terminal and bool(os.environ.get("KITTY_WINDOW_ID")) and scale != 1.0
    if not terminal:
        print(f"{gutter}{text}", end="\n" if newline else "", flush=True)
        return
    prefix = "\r\033[2K" + (f"{GUTTER_STYLE}{gutter}\033[0m" if gutter else "") + style
    suffix = "\033[0m"
    indent = len(gutter)
    columns = max(2, shutil.get_terminal_size((80, 24)).columns)
    available = max(1, columns - indent)
    if not scaled:
        if gutter:
            text = ("\n" + " " * indent).join(
                segment for raw_line in text.split("\n") for segment in _wrap_cells(_clean_line(raw_line), available))
        print(f"{prefix}{text}{suffix}", end="\n" if newline else "", flush=True)
        return

    # w=0 會讓 Kitty 每個字元各佔 s 個欄位，造成字元左右留白過大。
    # 將文字分成最多 w=7 的區塊；每個區塊共享寬度，字元會緊密排版。
    rows, numerator, denominator = SCALED_LAYOUT[scale]
    output = [prefix]
    for index, raw_line in enumerate(text.split("\n")):
        line = _clean_line(raw_line)
        if index:
            output.append(" " * indent)
        if scale > 1.0:
            output.append(_render_scaled_line(line, scale, available, indent))
        else:
            # s=1 keeps one cell per narrow character, so wrap like normal text.
            metadata = f"s={rows}:n={numerator}:d={denominator}:v=2"
            segments = _wrap_cells(line, available) if indent else [line]
            for number, segment in enumerate(segments):
                if number:
                    output.append("\n" * rows + " " * indent)
                for start in range(0, len(segment), 1024):
                    output.append(f"\033]66;{metadata};{segment[start:start + 1024]}\a")
        if newline:
            output.append("\n" * rows)
    output.append(suffix)
    print("".join(output), end="", flush=True)


class CaptionDisplay:
    """已完成字幕留在歷史；底部只保留最新一段中文預覽。"""

    def __init__(self, zh_scale, en_scale, show_zh, line_numbers=False, timestamps=False):
        self.zh_scale = zh_scale
        self.en_scale = en_scale
        self.show_zh = show_zh
        self.line_numbers = line_numbers
        self.timestamps = timestamps
        self.terminal = sys.stdout.isatty()
        self.preview = None
        self.has_translation = False
        self._received = {}  # caption ID -> receive time, until the caption completes
        self._last_id = 0

    def _gutter(self, caption_id=None):
        """Left metadata column; blank (same width) when caption_id is None."""
        parts = []
        if self.line_numbers:
            width = max(3, len(str(self._last_id)))
            parts.append(" " * width if caption_id is None else f"{caption_id:>{width}}")
        if self.timestamps:
            received = self._received.get(caption_id)
            parts.append(" " * 8 if received is None else time.strftime("%H:%M:%S", time.localtime(received)))
        return " ".join(parts) + "  " if parts else ""

    @staticmethod
    def _preview_rows(scale):
        return 2 if scale > 1.0 else 1

    def _clear_preview(self):
        if self.preview is None:
            return
        if self._preview_rows(self.preview[3]) == 2:
            print("\r\033[2K\033[1B\r\033[2K\033[1A", end="")
        else:
            print("\r\033[2K", end="")

    def _draw_preview(self):
        if self.preview is None:
            return
        caption_id, text, style, scale = self.preview
        rows = self._preview_rows(scale)
        gutter = self._gutter(caption_id)
        columns = shutil.get_terminal_size((80, 24)).columns - len(gutter)
        # 緊密區塊的實際寬度約為 scale 倍；不要再用 rows 將可見文字砍半。
        budget = max(0, int(columns / max(1.0, scale)) - 2)
        clipped = []
        for character in text:
            if ord(character) < 32 or 127 <= ord(character) <= 159:
                character = " "
            # 非 ASCII 保守預留兩格，確保中文預覽不換行。
            width = 1 if character.isascii() else 2
            if width > budget:
                clipped.append("…")
                break
            clipped.append(character)
            budget -= width
        if rows == 2:
            # 先預留第二列，避免底部的 multicell 字元捲動游標。
            print("\r\n\033[1A", end="")
        print_caption("".join(clipped), style, scale, newline=False, gutter=gutter)

    def _set_preview(self, caption_id, text, style, scale):
        self._clear_preview()
        self.preview = (caption_id, text, style, scale)
        self._draw_preview()

    def handle(self, event):
        """Render one caption event (see caption_relay.events)."""
        match event:
            case InterimText(text):
                self._interim(text)
            case FinalText(caption_id, text, received_at):
                self._final(caption_id, text, received_at)
            case TranslationReady(caption_id, text):
                self._translated(caption_id, text)
            case TranslationFailed(caption_id, error):
                self._failed(caption_id, error)
            case SessionStatus(message):
                self._status(message)
            case _:
                raise TypeError(f"Unsupported caption event: {event!r}")

    def _interim(self, text):
        if self.terminal:
            scale = 1.0 if self.show_zh else self.zh_scale
            self._set_preview(None, f"… {text[-60:]}", "\033[2m", scale)

    def _final(self, caption_id, text, received_at):
        self._last_id = max(self._last_id, caption_id)
        if self.timestamps:
            self._received[caption_id] = received_at
        if self.show_zh:
            self._clear_preview()
            self.preview = None
            print_caption(f"ZH  {text}", "\033[36m", self.zh_scale, gutter=self._gutter(caption_id))
        elif self.terminal:
            self._set_preview(caption_id, f"ZH  {text}", "\033[36m", self.zh_scale)

    def _translated(self, caption_id, text):
        self._clear_preview()
        if self.preview is not None and self.preview[0] == caption_id:
            self.preview = None
        if self.terminal and self.has_translation:
            # 分隔句子，不分隔同一句的折行；預留最後一格避免自動換行。
            columns = shutil.get_terminal_size((80, 24)).columns
            print("\r\033[2K\033[2;90m" + "─" * max(0, columns - 1) + "\033[0m", flush=True)
        self._last_id = max(self._last_id, caption_id)
        # 顯示中文時編號已在中文行；譯文只保留同寬空白欄。
        gutter = self._gutter(None if self.show_zh else caption_id)
        self._received.pop(caption_id, None)
        print_caption(text, "\033[1m", self.en_scale, gutter=gutter)
        self.has_translation = True
        # 較早一句翻譯完成時，保留較新一句的中文辨識進度。
        self._draw_preview()

    def _failed(self, caption_id, error):
        self._clear_preview()
        # 失敗時中文預覽仍保留，因此不移除其接收時間。
        print(f"{self._gutter(caption_id)}  [Translation failed: {error}]", flush=True)
        self._draw_preview()

    def _status(self, message):
        self._clear_preview()
        print(message, flush=True)
        self._draw_preview()

    def close(self):
        self._clear_preview()
        self.preview = None
        sys.stdout.flush()


