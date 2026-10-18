#!/data/data/com.termux/files/usr/bin/python

from __future__ import annotations
import argparse
import contextlib
import os
import select
import shutil
import sys
import termios
import tty


try:
    import pymupdf
except ImportError:
    sys.exit("PyMuPDF is required.  Install it with:  pip install PyMuPDF")
RESET = "\x1b[0m"
HOME = "\x1b[H"
CLEAR = "\x1b[2J"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
ENTER_ALT = "\x1b[?1049h"
LEAVE_ALT = "\x1b[?1049l"
REVERSE = "\x1b[7m"


class RenderError(RuntimeError):
    pass


def _wrap_line(text: str, width: int) -> list[str]:
    text = text.replace("\r", "").replace("\t", "    ").rstrip()
    if not text:
        return [""]
    out: list[str] = []
    while len(text) > width:
        cut = text.rfind(" ", 0, width + 1)
        if cut <= 0:
            cut = width
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
        if not text:
            return out
    out.append(text)
    return out


class TextExtractor:
    CACHE_LIMIT = 8

    def __init__(self, path: str) -> None:
        self.path = path
        try:
            self.doc = pymupdf.open(path)
        except Exception as exc:
            raise RenderError(str(exc)) from exc
        if self.doc.page_count == 0:
            msg = "document contains no pages"
            raise RenderError(msg)
        self._cache: dict[tuple[int, int], list[str]] = {}

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.doc.close()

    def page_count(self) -> int:
        return self.doc.page_count

    def page_lines(self, index: int, width: int) -> list[str]:
        width = max(1, width)
        key = (index, width)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        try:
            pdf_page = self.doc.load_page(index)
            blocks = pdf_page.get_text("blocks")
        except Exception as exc:
            msg = f"cannot extract page {index + 1}: {exc}"
            raise RenderError(msg) from exc
        lines: list[str] = []
        for block in blocks:
            if len(block) < 5:
                continue
            block_type = block[6] if len(block) > 6 else 0
            # 0 = text, 1 = image, other = other (annotations etc.)
            if block_type != 0:
                continue
            text = block[4]
            if not text:
                continue
            for para in text.split("\n"):
                if not para.strip():
                    lines.append("")
                    continue
                lines.extend(_wrap_line(para, width))
            lines.append("")
        while lines and lines[-1] == "":
            lines.pop()
        if len(self._cache) >= self.CACHE_LIMIT:
            self._cache.clear()
        self._cache[key] = lines
        return lines


def read_key(fd: int, timeout: float | None = None) -> str | None:
    ready, _, _ = select.select([fd], [], [], timeout)
    if not ready:
        return None
    first = os.read(fd, 1)
    if not first:
        return "q"
    if first != b"\x1b":
        return first.decode("utf-8", "replace")
    seq = bytearray(first)
    while len(seq) < 8:
        ready, _, _ = select.select([fd], [], [], 0.03)
        if not ready:
            break
        seq += os.read(fd, 1)
        if seq[-1:].isalpha() or seq[-1:] == b"~":
            break
    return seq.decode("latin-1")


class Viewer:
    def __init__(self, path: str, page: int = 1) -> None:
        self.path = path
        self.extractor = TextExtractor(path)
        self.page_count = self.extractor.page_count()
        if self.page_count == 0:
            msg = "document contains no pages"
            raise RenderError(msg)
        self.page_index = max(0, min(page - 1, self.page_count - 1))
        self.scroll = 0
        self.lines: list[str] = []
        self._lines_key: tuple[int, int] | None = None
        self.running = True

    def term_size(self) -> tuple[int, int]:
        size = shutil.get_terminal_size((80, 24))
        return size.columns, size.lines

    def view_rows(self) -> int:
        _, lines = self.term_size()
        return max(1, lines - 1)

    def load_lines(self) -> list[str]:
        cols, _ = self.term_size()
        key = (self.page_index, cols)
        if self._lines_key != key:
            self.lines = self.extractor.page_lines(self.page_index, cols)
            self._lines_key = key
        return self.lines

    def _clamp(self) -> None:
        try:
            lines = self.load_lines()
        except RenderError:
            self.scroll = 0
            return
        max_scroll = max(0, len(lines) - self.view_rows())
        self.scroll = max(0, min(self.scroll, max_scroll))

    def goto_page(self, index: int) -> None:
        if 0 <= index < self.page_count:
            self.page_index = index
            self.scroll = 0
            self._lines_key = None

    def draw(self) -> None:
        cols, _ = self.term_size()
        rows = self.view_rows()
        error: str | None = None
        try:
            lines = self.load_lines()
        except RenderError as exc:
            error = str(exc)
            lines = []
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            lines = []
        max_scroll = max(0, len(lines) - rows)
        self.scroll = max(0, min(self.scroll, max_scroll))
        buf: list[str] = [HOME]
        if error:
            buf.append(RESET)
            buf.append(f" {error} ".ljust(cols)[:cols])
            for _ in range(rows - 1):
                buf.append("\r\n")
        else:
            for i in range(rows):
                idx = self.scroll + i
                line = lines[idx] if idx < len(lines) else ""
                buf.append(line[:cols].ljust(cols))
                buf.append("\r\n")
        buf.append(RESET)
        buf.append(self._status(cols, error or "", len(lines), rows))
        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    def _status(self, cols: int, note: str, total: int, rows: int) -> str:
        name = os.path.basename(self.path)
        if note:
            line = f" {note} "
        else:
            max_scroll = max(0, total - rows)
            pct = 100 if max_scroll == 0 else round(100 * self.scroll / max_scroll)
            line = f" {name}  {self.page_index + 1}/{self.page_count}  {pct:3d}% "
        hint = " q quit  n/p page  j/k line  PgUp/PgDn scroll "
        if len(line) + len(hint) <= cols:
            line = line + " " * (cols - len(line) - len(hint)) + hint
        return REVERSE + line[:cols].ljust(cols) + RESET

    def handle(self, key: str) -> None:
        if key in ("q", "Q", "\x03") or key == "\x1b":
            self.running = False
            return
        if key in ("j", "\x1b[B", "\n", "\r"):
            self.scroll += 1
        elif key in ("k", "\x1b[A"):
            self.scroll -= 1
        elif key in (" ", "\x1b[6~", "f", "J"):
            self.scroll += self.view_rows()
        elif key in ("b", "\x1b[5~", "K"):
            self.scroll -= self.view_rows()
        elif key == "n":
            self.goto_page(self.page_index + 1)
            return
        elif key in ("N", "p"):
            self.goto_page(self.page_index - 1)
            return
        elif key in ("g", "\x1b[H", "\x1b[1~", "\x1b[7~", "\x1bOH"):
            self.scroll = 0
        elif key in ("G", "\x1b[F", "\x1b[4~", "\x1b[8~", "\x1bOF"):
            self.scroll = 1 << 30
        self._clamp()

    def run(self, fd: int) -> None:
        dirty = True
        last_size = (0, 0)
        while self.running:
            size = self.term_size()
            if size != last_size:
                last_size = size
                dirty = True
            if dirty:
                self.draw()
                dirty = False
            key = read_key(fd, 0.25)
            if key is None:
                continue
            self.handle(key)
            dirty = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tpv",
        description="View the text of a PDF file in the terminal (PyMuPDF backend).",
    )
    parser.add_argument("file", help="path to the PDF file")
    parser.add_argument("-p", "--page", type=int, default=1, help="page to open first (1-based, default 1)")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.file):
        parser.error(f"no such file: {args.file}")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("must be run from an interactive terminal")
    try:
        viewer = Viewer(args.file, args.page)
    except Exception as exc:
        sys.exit(f"tpv: could not open {args.file!r}: {exc}")
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        sys.stdout.write(ENTER_ALT + HIDE_CURSOR + CLEAR + HOME)
        sys.stdout.flush()
        viewer.run(fd)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        sys.stdout.write(RESET + SHOW_CURSOR + LEAVE_ALT)
        sys.stdout.flush()
        viewer.extractor.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
