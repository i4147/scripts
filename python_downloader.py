#!/data/data/com.termux/files/home/.local/bin/python
"""
dl - a small pip-style download manager for the command line.

Usage:
    dl https://example.com/file.iso
    dl -d ~/Downloads -j 4 url1 url2 url3
    dl -o movie.mp4 https://example.com/video
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

__version__ = "1.0.0"

CHUNK = 64 * 1024
UA = f"dl/{__version__} (pip-style download manager)"
FULL, HEAD, EMPTY = "━", "╸", " "

# Set by Ctrl-C so worker threads bail out promptly.
STOP = threading.Event()


# --------------------------------------------------------------------------
# formatting helpers (pip-flavoured)
# --------------------------------------------------------------------------

def fmt_size(n: float) -> str:
    """Format a byte count the way pip does (SI units)."""
    if n is None:
        return "?"
    if n > 1000 * 1000:
        return f"{n / 1e6:.1f} MB"
    if n > 10 * 1000:
        return f"{n / 1000:.0f} kB"
    if n > 1000:
        return f"{n / 1000:.1f} kB"
    return f"{n:.0f} bytes"


def fmt_pair(done: float, total: float) -> str:
    """`9.2/10.1 MB` - both numbers share a unit, like pip."""
    if total < 1000:
        return f"{done:.0f}/{total:.0f} bytes"
    if total < 1000 * 1000:
        return f"{done / 1e3:.1f}/{total / 1e3:.1f} kB"
    return f"{done / 1e6:.1f}/{total / 1e6:.1f} MB"


def fmt_time(seconds: float) -> str:
    """`0:00:09` / `1:02:03`."""
    if seconds is None or seconds < 0 or seconds != seconds:
        return "--:--:--"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def fmt_bar(fraction: float | None, width: int, spin: int = 0) -> str:
    """`━━━━━━━╸      ` ; `fraction=None` gives an indeterminate bar."""
    if width <= 0:
        return ""
    if fraction is None:
        block = max(1, width // 5)
        pos = spin % (width + block) - block
        return "".join(FULL if pos <= i < pos + block else EMPTY for i in range(width))
    frac = min(max(fraction, 0.0), 1.0)
    filled = int(frac * width)
    if filled >= width:
        return FULL * width
    return FULL * filled + HEAD + EMPTY * (width - filled - 1)


def shorten(url: str, n: int = 42) -> str:
    name = os.path.basename(urllib.parse.urlparse(url).path) or url
    return name if len(name) <= n else name[: n - 1] + "…"


# --------------------------------------------------------------------------
# progress bars
# --------------------------------------------------------------------------

class Bar:
    """State + rendering for a single download."""

    def __init__(self, label: str, total: int | None = None):
        self.label = label
        self.total = total
        self.done = 0
        self.speed = 0.0
        self.spin = 0
        self.finished = False
        self.failed = False
        self.error: str | None = None
        self.start = time.monotonic()
        self._last_t = self.start
        self._last_d = 0

    @property
    def elapsed(self) -> float:
        return max(time.monotonic() - self.start, 1e-6)

    def _tick(self) -> None:
        now = time.monotonic()
        dt = now - self._last_t
        if dt < 0.15:
            return
        inst = (self.done - self._last_d) / dt
        self.speed = inst if self.speed <= 0 else 0.6 * self.speed + 0.4 * inst
        self._last_t, self._last_d = now, self.done

    def _eta(self) -> float | None:
        if not self.total or self.speed <= 0:
            return None
        return max(self.total - self.done, 0) / self.speed

    def render(self, width: int) -> str:
        if self.failed:
            return f"{self.label}: error: {self.error}"
        if self.finished:
            el = self.elapsed
            rate = self.done / el if el > 0 else 0.0
            return f"{self.label}  {fmt_size(self.done)} in {fmt_time(el)} ({fmt_size(rate)}/s)"

        self._tick()

        if self.total:
            frac: float | None = self.done / self.total
            head = fmt_pair(self.done, self.total)
            parts = [head, f"{fmt_size(self.speed)}/s", f"eta {fmt_time(self._eta())}"]
        else:
            frac = None
            parts = [fmt_size(self.done), f"{fmt_size(self.speed)}/s"]

        tail = "  ".join(parts)
        room = width - len(tail) - 1
        prefix = ""
        if len(self.label) + 12 <= room:
            prefix = self.label + " "
            room -= len(prefix)
        if room < 5:
            return tail
        return prefix + fmt_bar(frac, room, self.spin) + " " + tail


class Progress:
    """Renders N bars in place using ANSI cursor movement."""

    def __init__(self, stream=None, enabled: bool | None = None, final: bool = True):
        self.stream = stream if stream is not None else sys.stdout
        if enabled is None:
            enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self.enabled = enabled
        self.final = final
        self.bars: list[Bar] = []
        self.lock = threading.RLock()
        self._drawn = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add(self, bar: Bar) -> None:
        with self.lock:
            self.bars.append(bar)

    def __enter__(self) -> "Progress":
        if self.enabled:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    def _loop(self) -> None:
        while not self._stop.wait(0.1):
            self.refresh()

    def refresh(self) -> None:
        with self.lock:
            for b in self.bars:
                b.spin += 1
            self._paint()

    def _width(self) -> int:
        return max(shutil.get_terminal_size((80, 24)).columns - 1, 24)

    def _paint(self) -> None:
        if not self.bars:
            return
        width = self._width()
        lines = [b.render(width) for b in self.bars]
        out = []
        if self._drawn:
            out.append(f"\x1b[{self._drawn}A")
        for ln in lines:
            out.append("\x1b[2K" + ln + "\n")
        self.stream.write("".join(out))
        self.stream.flush()
        self._drawn = len(lines)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

        with self.lock:
            if self.enabled and self._drawn:
                out = [f"\x1b[{self._drawn}A"]
                out.extend(["\x1b[2K\n"] * self._drawn)
                out.append(f"\x1b[{self._drawn}A")
                self.stream.write("".join(out))
                self._drawn = 0

            if self.final:
                width = self._width()
                for b in self.bars:
                    self.stream.write(b.render(width) + "\n")
            self.stream.flush()


# --------------------------------------------------------------------------
# filename helpers
# --------------------------------------------------------------------------

_CD_STAR = re.compile(r"filename\*\s*=\s*[^']*''([^;]+)", re.I)
_CD_QUOTED = re.compile(r'filename\s*=\s*"([^"]*)"', re.I)
_CD_BARE = re.compile(r"filename\s*=\s*([^;]+)", re.I)


def _sanitize(name: str) -> str:
    name = os.path.basename(name.replace("\\", "/")).strip().strip('"')
    return "" if name in ("", ".", "..") else name


def guess_filename(url: str, headers) -> str:
    cd = headers.get("Content-Disposition") if headers else None
    if cd:
        for pattern, group in ((_CD_STAR, 1), (_CD_QUOTED, 1), (_CD_BARE, 1)):
            m = pattern.search(cd)
            if m:
                name = _sanitize(urllib.parse.unquote(m.group(group)))
                if name:
                    return name
    path = urllib.parse.urlparse(url).path
    return _sanitize(urllib.parse.unquote(os.path.basename(path))) or "index.html"


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    i = 1
    while True:
        candidate = f"{root} ({i}){ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1


def part_path(outdir: str, url: str, dest: str | None) -> str:
    if dest is not None:
        return dest + ".part"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return os.path.join(outdir, f".dl-{digest}.part")


# --------------------------------------------------------------------------
# the download itself
# --------------------------------------------------------------------------

def download_one(
    progress: Progress,
    url: str,
    outdir: str,
    dest: str | None = None,
    resume: bool = True,
    timeout: float = 30.0,
) -> str:
    bar = Bar(shorten(url))
    progress.add(bar)

    try:
        tmp = part_path(outdir, url, dest)

        offset = 0
        if resume and os.path.exists(tmp):
            offset = os.path.getsize(tmp)

        headers = {"User-Agent": UA, "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)

            # Server ignored our Range header -> start over.
            if offset and status != 206:
                offset = 0

            final = dest if dest is not None else unique_path(
                os.path.join(outdir, guess_filename(url, resp.headers))
            )
            bar.label = os.path.basename(final)

            length = resp.headers.get("Content-Length")
            total = int(length) + offset if length is not None else None
            bar.total = total
            bar.done = offset

            with open(tmp, "ab" if offset else "wb") as fh:
                while not STOP.is_set():
                    data = resp.read(CHUNK)
                    if not data:
                        break
                    fh.write(data)
                    bar.done += len(data)

            if STOP.is_set():
                raise KeyboardInterrupt
            if total is not None and bar.done < total:
                raise IOError(f"truncated download ({bar.done}/{total} bytes)")

        os.replace(tmp, final)
        bar.finished = True
        return final

    except BaseException as exc:  # noqa: BLE001 - we re-raise
        bar.failed = True
        bar.error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dl",
        description="pip-style download manager",
        epilog="example: dl -d ~/Downloads -j 4 https://example.com/a.iso https://example.com/b.iso",
    )
    p.add_argument("urls", nargs="+", metavar="URL", help="URL(s) to download")
    p.add_argument("-o", "--output", metavar="PATH",
                   help="output file (single URL only)")
    p.add_argument("-d", "--dir", default=".", metavar="DIR",
                   help="output directory (default: .)")
    p.add_argument("-j", "--jobs", type=int, default=4, metavar="N",
                   help="parallel downloads (default: 4)")
    p.add_argument("--no-resume", action="store_true",
                   help="ignore partial files and restart from scratch")
    p.add_argument("--timeout", type=float, default=30.0, metavar="SECS",
                   help="socket timeout in seconds (default: 30)")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress output")
    p.add_argument("-V", "--version", action="version",
                   version=f"dl {__version__}")
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.output and len(args.urls) > 1:
        parser.error("-o/--output can only be used with a single URL")
    if args.jobs < 1:
        parser.error("-j/--jobs must be >= 1")

    outdir = os.path.abspath(args.dir)
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError as exc:
        print(f"dl: cannot create {outdir}: {exc}", file=sys.stderr)
        return 2

    resume = not args.no_resume
    fixed_dest = os.path.abspath(args.output) if args.output else None

    stream = sys.stdout
    progress = Progress(
        stream,
        enabled=(not args.quiet) and stream.isatty(),
        final=not args.quiet,
    )

    done: list[str] = []
    failed: list[tuple[str, BaseException]] = []
    interrupted = False
    t0 = time.monotonic()

    pool = ThreadPoolExecutor(max_workers=min(args.jobs, len(args.urls)))
    try:
        with progress:
            futures = [
                (pool.submit(download_one, progress, url, outdir,
                             fixed_dest if i == 0 else None, resume, args.timeout), url)
                for i, url in enumerate(args.urls)
            ]
            try:
                for fut, url in futures:
                    pass  # submitted; now wait
                for fut in as_completed([f for f, _ in futures]):
                    url = next(u for f, u in futures if f is fut)
                    try:
                        done.append(fut.result())
                    except KeyboardInterrupt:
                        raise
                    except BaseException as exc:  # noqa: BLE001
                        failed.append((url, exc))
            except KeyboardInterrupt:
                interrupted = True
                STOP.set()
                for f, _ in futures:
                    f.cancel()
    finally:
        STOP.set()
        pool.shutdown(wait=True, cancel_futures=True)

    elapsed = time.monotonic() - t0

    if not args.quiet:
        total_bytes = 0
        for path in done:
            try:
                total_bytes += os.path.getsize(path)
            except OSError:
                pass
        if interrupted:
            print("interrupted", file=sys.stderr)
        for url, exc in failed:
            print(f"dl: {url}: {exc}", file=sys.stderr)
        if done:
            print(f"Downloaded {len(done)} file(s), "
                  f"{fmt_size(total_bytes)} in {fmt_time(elapsed)}")

    return 130 if interrupted else (1 if failed else 0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
