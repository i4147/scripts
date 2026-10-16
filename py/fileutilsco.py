from __future__ import annotations

import functools
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from multiprocessing import get_context
from os import scandir as os_scandir
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, overload

from .const import BIN_EXT, EMULATED, IMGEXT, SDCARD, SKIP_DIRS, THRESHOLD, TXT_EXT
from .isbinary import is_binary

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator


@overload
def get_file_age(path: str | Path, str_mode: bool = False) -> float: ...


@overload
def get_file_age(path: str | Path, str_mode: bool = True) -> str: ...


class _FileReader:
    def __init__(self, path: str | Path, keep_ends: bool = True):
        self.path = Path(path)
        self.keep_ends = keep_ends

    def read(self) -> list[str]:
        if self.path.stat().st_size > THRESHOLD:
            return self._read_with_mmap()
        return self._read_direct()

    def _read_direct(self) -> list[str]:
        data = self.path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines(keepends=self.keep_ends)
        if lines and not lines[-1].endswith(("\n", "\r\n", "\r")) and data.endswith(b"\n"):
            lines.append("")
        return lines

    def _read_with_mmap(self) -> list[str]:
        import mmap

        size = self.path.stat().st_size
        with self.path.open("rb") as f, mmap.mmap(f.fileno(), size, access=mmap.ACCESS_READ) as mm:
            text = mm[:].decode("utf-8", errors="replace")
        lines = text.splitlines(keepends=self.keep_ends)
        if lines and not lines[-1].endswith(("\n", "\r\n", "\r")) and size > 0 and text.endswith("\n"):
            lines.append("")
        return lines


def read_lines(path: str | Path, ke: bool = True) -> list[str]:
    reader = _FileReader(path, keep_ends=ke)
    return reader.read()


def read_lines_mmap(path: Path, keep_ends: bool = True) -> list[str]:
    import mmap

    size = path.stat().st_size
    with path.open("rb") as f, mmap.mmap(f.fileno(), size, access=mmap.ACCESS_READ) as mm:
        text = mm[:].decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=keep_ends)
    if lines and not lines[-1].endswith(("\n", "\r\n", "\r")) and size > 0 and text.endswith("\n"):
        lines.append("")
    return lines


class _ExtensionAnalyzer:
    MULTIPART_PREFIXES = frozenset({".tar", ".min", ".bundle", ".log", ".spec", ".test", ".d", ".module"})
    ARCHIVE_SUFFIXES = frozenset({".gz", ".xz", ".bz2", ".zst", ".lz"})

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.suffixes = self.path.suffixes

    def analyze(self) -> str:
        if not self.suffixes:
            return ""
        if len(self.suffixes) == 1:
            return self.suffixes[0]
        return self._handle_multipart()

    def _handle_multipart(self) -> str:
        if self.suffixes[0] in self.MULTIPART_PREFIXES:
            return "".join(self.suffixes)
        if len(self.suffixes) >= 2:
            if self.suffixes[-1] in self.ARCHIVE_SUFFIXES and self.suffixes[-2] == ".tar":
                return f".tar{self.suffixes[-1]}"
        return self.suffixes[-1]


def gext(path: str | Path) -> str:
    analyzer = _ExtensionAnalyzer(path)
    return analyzer.analyze()


class _DirectoryWalker:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.dirs: list[Path] = []

    def walk(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        stack = [self.root]
        while stack:
            current = stack.pop()
            try:
                with os_scandir(current) as entries:
                    subdirs = [Path(entry.path) for entry in entries if entry.is_dir(follow_symlinks=False)]
                    self.dirs.extend(subdirs)
                    stack.extend(subdirs)
            except (PermissionError, OSError):
                continue
        return self.dirs


def get_dirs(path: str | Path) -> list[Path]:
    walker = _DirectoryWalker(path)
    return walker.walk()


class _FileAgeCalculator:
    TIME_UNITS = (
        ("y", 365 * 24 * 60 * 60),
        ("m", 30 * 24 * 60 * 60),
        ("d", 24 * 60 * 60),
        ("h", 60 * 60),
        ("min", 60),
        ("sec", 1),
    )

    def __init__(self, path: str | Path):
        from os import stat as os_stat
        from time import time as time_time

        self.path = Path(path)
        self.current_time = time_time()
        self.file_age = self._compute_age()

    def _compute_age(self) -> float:
        from os import stat as os_stat

        if not self.path.exists():
            return -1.0
        if not self.path.is_file():
            return -2.0
        file_stat = os_stat(self.path)
        return self.current_time - file_stat.st_ctime

    def as_float(self) -> float:
        if self.file_age < 0:
            return 0.0
        return self.file_age

    def as_string(self) -> str:
        if self.file_age < 0:
            return "0 sec"
        int_age = int(self.file_age)
        if int_age < 0:
            return "0 sec"
        return self._format_parts(int_age)

    def _format_parts(self, age_seconds: int) -> str:
        parts = []
        for name, seconds_per_unit in self.TIME_UNITS:
            value, age_seconds = divmod(age_seconds, seconds_per_unit)
            if value:
                parts.append(f"{value} {name}")
        return ", ".join(parts) if parts else "0 sec"


def get_file_age(path: str | Path, str_mode: bool = False) -> float | str:
    calculator = _FileAgeCalculator(path)
    if str_mode:
        return calculator.as_string()
    return calculator.as_float()


def _normalize_name(name: str) -> str:
    from re import sub as re_sub

    return re_sub(r"[-_.]+", "-", name).lower()


@functools.lru_cache(maxsize=1024 * 1024)
def get_installed_packages() -> dict[str, str]:
    from importlib import metadata
    from operator import itemgetter

    packages = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        version = distribution.metadata.get("Version")
        if name and version:
            packages[_normalize_name(name)] = version
    return dict(sorted(packages.items(), key=itemgetter(0)))


@functools.lru_cache(maxsize=1024 * 1024)
def get_installed_pkgs() -> list[str]:
    from importlib import metadata

    packages = []
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            packages.append(_normalize_name(name))
    return sorted(packages)


def get_mime_type(path: str | Path) -> str | None:
    from mimetypes import guess_type

    return guess_type(str(path))[0]


def get_random_filename(length: int = 10) -> str:
    from secrets import choice
    from string import ascii_lowercase

    return "".join(choice(ascii_lowercase) for _ in range(length))


def is_image(path: str | Path) -> bool:
    path = Path(path)
    try:
        return path.is_file() and path.suffix in IMGEXT
    except Exception:
        return False


def is_within(child_path: str | Path, parent_path: str | Path) -> bool:
    child = Path(child_path).resolve()
    parent = Path(parent_path).resolve()
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


class _FilenameNormalizer:
    def __init__(self, path: str | Path):
        self.path = str(path)

    def normalize(self) -> str:
        from re import compile as re_compile, escape as re_escape

        special_chars = '<>:"/\\|?*' + "".join(map(chr, range(32)))
        pattern = re_compile("|".join(map(re_escape, special_chars)))
        return pattern.sub("_", self.path)


def normalize_filename(path: str | Path) -> str:
    normalizer = _FilenameNormalizer(path)
    return normalizer.normalize()


def normalize_path(path: str | Path) -> Path:
    pathstr = str(path)
    if EMULATED in pathstr:
        return Path(pathstr.replace(EMULATED, SDCARD))
    return Path(path).resolve()


def reverse_dict(input_dict: dict) -> dict:
    rev: dict[Any, Any] = {}
    for k, v in input_dict.items():
        if v in rev:
            existing = rev[v]
            if isinstance(existing, list):
                existing.append(k)
            else:
                rev[v] = [existing, k]
        else:
            rev[v] = k
    return rev


class _FileSizeFormatter:
    UNITS = ("B", "KB", "MB", "GB", "TB")

    def format(self, sz: float) -> str:
        sz = abs(int(sz))
        if sz == 0:
            return "0 B"
        idx = min((sz.bit_length() - 1) // 10, len(self.UNITS) - 1)
        value = sz / (1024**idx)
        if idx == 0:
            return f"{int(value)} {self.UNITS[idx]}"
        return f"{value:.1f} {self.UNITS[idx]}"


def fsz(sz: float) -> str:
    formatter = _FileSizeFormatter()
    return formatter.format(sz)


def safe_delete(path: Path, max_retries: int = 3) -> bool:
    from shutil import rmtree as shutil_rmtree

    try:
        if path.is_dir():
            shutil_rmtree(path)
        else:
            path.unlink()
        return True
    except (FileNotFoundError, PermissionError, OSError, Exception):
        return False


def get_filez(root_dir: str | Path, ext: list[str] | None = None) -> Iterator[Path]:
    from fastwalk import walk_files

    ext_set = set(ext) if ext else None
    for pth in walk_files(root_dir):
        path = Path(pth)
        if should_skip(path):
            continue
        if path.is_file() and (ext_set is None or path.suffix in ext_set):
            yield path


class _UniquePathFinder:
    def __init__(self, path: Path | str):
        self.path = _clean_fname(Path(path))
        self.parent = self.path.parent
        self.name_parts = self._extract_name_parts()

    def _extract_name_parts(self) -> tuple[str, str]:
        suffixes = self.path.suffixes
        if suffixes:
            first_suffix_idx = self.path.name.find(suffixes[0])
            stem = self.path.name[:first_suffix_idx]
            full_suffix = "".join(suffixes)
        else:
            stem = self.path.name
            full_suffix = ""
        return (stem, full_suffix)

    def find(self) -> Path:
        if not self.path.exists():
            return self.path
        stem, full_suffix = self.name_parts
        counter = 1
        while True:
            new_path = self.parent / f"{stem}_{counter}{full_suffix}"
            if not new_path.exists():
                return new_path
            counter += 1


def unique_path(path: Path | str) -> Path:
    finder = _UniquePathFinder(path)
    return finder.find()


def _clean_fname(path: Path) -> Path:
    from re import sub as re_sub

    clean_name = re_sub(r"(_\d+)+", "", path.name)
    return path.with_name(clean_name)


class _TimeFormatter:
    @staticmethod
    def format(t: float) -> str:
        if t <= 0:
            return "0s"
        if t < 1:
            return _TimeFormatter._format_subsecond(t)
        if t < 60:
            return f"{t:.0f}s"
        if t < 3600:
            return _TimeFormatter._format_minutes(t)
        if t < 86400:
            return _TimeFormatter._format_hours(t)
        if t < 86400 * 30:
            return _TimeFormatter._format_days(t)
        return _TimeFormatter._format_months(t)

    @staticmethod
    def _format_subsecond(t: float) -> str:
        ms = t * 1000
        if ms < 1:
            return f"{ms * 1000:.0f}µs"
        return f"{ms:.2f}ms"

    @staticmethod
    def _format_minutes(t: float) -> str:
        minutes = int(t // 60)
        secs = int(t % 60)
        result = f"{minutes}m"
        if secs:
            result += f", {secs}s"
        return result

    @staticmethod
    def _format_hours(t: float) -> str:
        hours = int(t // 3600)
        remaining = t % 3600
        minutes = int(remaining // 60)
        secs = int(remaining % 60)
        result = f"{hours}h"
        if minutes:
            result += f", {minutes}m"
        if secs:
            result += f", {secs}s"
        return result

    @staticmethod
    def _format_days(t: float) -> str:
        days = int(t // 86400)
        remaining = t % 86400
        hours = int(remaining // 3600)
        minutes = int(remaining % 3600 // 60)
        result = f"{days}d"
        if hours:
            result += f", {hours}h"
        if minutes:
            result += f", {minutes}m"
        return result

    @staticmethod
    def _format_months(t: float) -> str:
        months = t / (86400 * 30)
        if months < 1:
            return "less than 1 month"
        return f"{months:.2f} months"


def format_time(t: float) -> str:
    return _TimeFormatter.format(t)


class _CommandRunner:
    def __init__(
        self, cmd: list[str], run_silently: bool = False, show_output: bool = True, timeout: float | None = None
    ):
        self.cmd = cmd
        self.run_silently = run_silently
        self.show_output = show_output
        self.timeout = timeout

    def run(self) -> tuple[int, str, str]:
        from subprocess import DEVNULL as _DEVNULL, TimeoutExpired as subprocess_TimeoutExpired, run as subprocess_run
        from sys import stderr as sys_stderr, stdout as sys_stdout

        if not self.cmd:
            msg = "cmd must be a non-empty list (e.g., ['ls', '-l'])"
            raise ValueError(msg)

        try:
            if self.run_silently:
                result = subprocess_run(self.cmd, stdout=_DEVNULL, stderr=_DEVNULL, timeout=self.timeout)
                return (result.returncode, "", "")

            result = subprocess_run(self.cmd, capture_output=True, text=True, timeout=self.timeout)
            stdout, stderr = (result.stdout, result.stderr)

            if self.show_output:
                self._output_streams(stdout, stderr, sys_stdout, sys_stderr)

            return (result.returncode, stdout, stderr)

        except FileNotFoundError:
            return self._handle_error(127, "Command not found", sys_stderr)
        except PermissionError:
            return self._handle_error(126, "Permission denied", sys_stderr)
        except subprocess_TimeoutExpired:
            return self._handle_timeout(sys_stderr)
        except Exception as e:
            return self._handle_unexpected(e, sys_stderr)

    def _output_streams(self, stdout: str, stderr: str, sys_stdout, sys_stderr) -> None:
        if stdout:
            sys_stdout.write(stdout)
            sys_stdout.flush()
        if stderr:
            sys_stderr.write(stderr)
            sys_stderr.flush()

    def _handle_error(self, code: int, error_type: str, sys_stderr) -> tuple[int, str, str]:
        msg = f"{error_type}: '{self.cmd[0]}'"
        if self.show_output and not self.run_silently:
            print(msg, file=sys_stderr)
        return (code, "", msg)

    def _handle_timeout(self, sys_stderr) -> tuple[int, str, str]:
        msg = f"Command timed out after {self.timeout}s: {' '.join(self.cmd)}"
        if self.show_output and not self.run_silently:
            print(msg, file=sys_stderr)
        return (124, "", msg)

    def _handle_unexpected(self, e: Exception, sys_stderr) -> tuple[int, str, str]:
        msg = f"Unexpected error running '{self.cmd[0]}': {e}"
        if self.show_output and not self.run_silently:
            print(msg, file=sys_stderr)
        return (1, "", msg)


def runcmd(
    cmd: list[str], run_silently: bool = False, show_output: bool = True, timeout: float | None = None
) -> tuple[int, str, str]:
    runner = _CommandRunner(cmd, run_silently, show_output, timeout)
    return runner.run()


def write_txt_file(path: str | Path, data: str, overwrite: bool = False) -> bool:
    if not isinstance(data, str):
        return False
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not overwrite:
            return False
        path.write_text(data, encoding="utf-8")
        return True
    except Exception:
        return False


def should_skip(path: str | Path) -> bool:
    path = Path(path)
    return bool(path.is_symlink() or not SKIP_DIRS.isdisjoint(path.parts))


def append_text(path: str | Path, content: str, encoding: str = "utf-8") -> bool:
    path = Path(path)
    if path.is_symlink() or path.is_dir():
        return False
    if not path.exists():
        path.write_text(content, encoding=encoding)
        return True
    with path.open("a", encoding=encoding) as f:
        f.write("\n")
        f.write(content)
    return True


def get_removed_lines(txt1: str, txt2: str) -> list[str]:
    set1 = {l for l in txt1.splitlines() if l}
    set2 = {l for l in txt2.splitlines() if l}
    return list(set1 - set2)


def restore_bak(path: str | Path) -> bool:
    path = Path(path)
    bak_path = path.with_name(path.name + ".bak")
    if bak_path.exists():
        bak_path.rename(path)
        return True
    return False


BOLD = "\x1b[1m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[36m"
RED = "\x1b[31m"
RESET = "\x1b[0m"
DIM = "\x1b[2m"


def rrs(path, before: int, after: int) -> None:
    saved = before - after
    if not saved:
        msg = f"\x1b[5;92mNO CHANGE\x1b[0m"
    else:
        ratio = (1 - (after / before)) * 100
        sign = "+" if saved > 0 else "-"
        msg = f"\x1b[5;92m{before}->{after} = {sign} \x1b[5;94m{fsz(saved)}\x1b[0m | \x1b[5;96m{ratio:.1f}\x1b[5;91m%\x1b[0m"
    print(f"{path.name}|{msg}\n")


def is_empty(path: str | Path) -> bool:
    path = Path(path)
    return path.is_dir() and not any(path.iterdir())


class _FileCollector:
    def __init__(self, path: str | Path, include_hidden: bool = True, ext: list[str] | None = None):
        self.path = Path(path)
        self.include_hidden = include_hidden
        self.ext_tuple = tuple(ext) if ext else None
        self.files: list[Path] = []

    def collect(self) -> list[Path]:
        if not self.path.exists():
            msg = f"Path does not exist: {self.path}"
            raise FileNotFoundError(msg)
        if not self.path.is_dir():
            msg = f"Path is not a directory: {self.path}"
            raise NotADirectoryError(msg)

        stack: list[Path] = [self.path]
        while stack:
            current = stack.pop()
            try:
                with os_scandir(current) as entries:
                    self._process_entries(entries, stack)
            except (PermissionError, OSError):
                continue
        return sorted(self.files)

    def _process_entries(self, entries, stack: list[Path]) -> None:
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in SKIP_DIRS:
                    stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                self._check_file(Path(entry.path))

    def _check_file(self, file_path: Path) -> None:
        if not self.include_hidden and file_path.name.startswith("."):
            return
        if self.ext_tuple is None or file_path.name.endswith(self.ext_tuple):
            self.files.append(file_path)


def get_files_scandir(path: str | Path, include_hidden: bool = True, ext: list[str] | None = None) -> list[Path]:
    collector = _FileCollector(path, include_hidden, ext)
    return collector.collect()


def get_fast(path, ext: list[str] | None = None) -> Iterator[Path]:
    from fastwalk import walk_files

    for entry in walk_files(path):
        if should_skip(entry):
            continue
        if ext is None or entry.suffix in ext:
            yield entry


def get_files_iter(directory: str | Path, ext: list[str] | None = None) -> Iterator[Path]:
    directory = Path(directory)
    if not directory.is_dir():
        msg = f"Path is not a directory: {directory}"
        raise NotADirectoryError(msg)
    ext_set = set(ext) if ext else None
    with os_scandir(directory) as entries:
        for entry in entries:
            path = Path(entry.path)
            if path.is_symlink():
                continue
            if path.is_file():
                if ext_set is None or path.suffix in ext_set:
                    yield path.resolve()
            elif path.is_dir():
                yield from get_files_iter(path, ext)


class _BFSFileWalker:
    def __init__(self, path: str | Path, ext: list[str] | None = None):
        self.path = Path(path)
        self.ext = ext

    def walk(self) -> list[Path]:
        from collections import deque

        queue = deque([self.path])
        files = []
        while queue:
            current = queue.popleft()
            try:
                entries = current.iterdir()
            except (PermissionError, OSError):
                continue
            for item in entries:
                if item.is_symlink():
                    continue
                if item.is_dir() and item.name not in SKIP_DIRS:
                    queue.append(item)
                elif item.is_file() and (self.ext is None or item.suffix in self.ext):
                    files.append(item)
        return sorted(files)


def get_files(path: str | Path, ext: list[str] | None = None) -> list[Path]:
    walker = _BFSFileWalker(path, ext)
    return walker.walk()


def getfiles(root_dir: str | Path, ext: list[str] | None = None) -> list[Path]:
    from fastwalk import walk_files

    files = []
    for path in walk_files(root_dir):
        if should_skip(path):
            continue
        if path.is_file() and (ext is None or (path.suffix and path.suffix in ext)):
            files.append(path)
    return sorted(files)


def get_files_pathlib(path: Path, include_hidden: bool = True, ext: list[str] | None = None) -> list[Path]:
    if not path.exists():
        msg = f"Path does not exist: {path}"
        raise FileNotFoundError(msg)
    if not path.is_dir():
        msg = f"Path is not a directory: {path}"
        raise NotADirectoryError(msg)
    files: list[Path] = []
    stack: list[Path] = [path]
    while stack:
        current = stack.pop()
        try:
            for entry in current.iterdir():
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in SKIP_DIRS:
                        stack.append(entry)
                elif entry.is_file():
                    if not include_hidden and entry.name.startswith("."):
                        continue
                    if ext is None or entry.suffix.lower() in ext:
                        files.append(entry)
        except PermissionError:
            continue
    return sorted(files)


def get_files4(path: str | Path, include_hidden: bool = True, ext: list[str] | None = None) -> list[Path]:
    path = Path(path)
    if not path.exists():
        msg = f"Path does not exist: {path}"
        raise FileNotFoundError(msg)
    if not path.is_dir():
        msg = f"Path is not a directory: {path}"
        raise NotADirectoryError(msg)
    ext_tuple = tuple(ext) if ext is not None else None
    files = []
    stack: list[Path] = [path]
    while stack:
        current = stack.pop()
        try:
            with os_scandir(current) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in SKIP_DIRS:
                            stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        if not include_hidden and entry.name.startswith("."):
                            continue
                        if ext_tuple is None or entry.name.endswith(ext_tuple):
                            files.append(Path(entry.path))
        except (PermissionError, OSError):
            continue
    return sorted(files)


def get_nobinary(path: str | Path) -> list[Path]:
    return [f for f in get_files(path) if not is_binary(f)]


def get_pyfiles_iter(root: Path) -> Generator[Path, None, None]:
    root = Path(root)
    try:
        for entry in root.iterdir():
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name in {".git", "__pycache__"}:
                    continue
                yield from get_pyfiles_iter(entry)
            elif entry.is_file() and is_python_file(entry):
                yield entry
    except PermissionError:
        pass


class _DirSizeCalculator:
    def __init__(self, path: Path):
        self.path = path

    def calculate(self) -> int | float:
        if not isinstance(self.path, (Path, str)):
            return 0
        p = Path(self.path)
        if p.is_symlink():
            return 0
        if p.is_file():
            return p.stat().st_size
        if p.is_dir():
            return self._compute_dir_size(p)
        return 0

    def _compute_dir_size(self, path: Path) -> int:
        from concurrent.futures import ThreadPoolExecutor

        total = 0
        with ThreadPoolExecutor() as executor:
            futures = []
            for item in path.iterdir():
                if item.is_symlink():
                    continue
                elif item.is_file():
                    total += item.stat().st_size
                elif item.is_dir():
                    futures.append(executor.submit(self._compute_dir_size, item))
            for future in futures:
                total += future.result()
        return total


def gsz(path: str | Path) -> int | float:
    calculator = _DirSizeCalculator(Path(path))
    return calculator.calculate()


def _dir_size(path: Path) -> int:
    calculator = _DirSizeCalculator(path)
    return calculator._compute_dir_size(path)


def _copy_file(args: tuple[Path, Path]) -> tuple[bool, Path, Exception | None]:
    from shutil import copy2

    src_file, dest_file = args
    try:
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        copy2(src_file, dest_file)
        return (True, dest_file, None)
    except Exception as e:
        return (False, dest_file, e)


def _collect_files(src_dir: Path) -> list[Path]:
    return list(src_dir.rglob("*")) if src_dir.is_dir() else []


class _DirectoryCopier:
    def __init__(self, src: str, dest: str):
        self.src_path = Path(src).resolve()
        self.dest_path = Path(dest).resolve()

    def copy(self) -> bool:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        try:
            self._validate_source()
            dest_folder = self.dest_path / self.src_path.name
            dest_folder.mkdir(parents=True, exist_ok=True)

            files = _collect_files(self.src_path)
            if not files:
                return True

            tasks = self._prepare_tasks(files, dest_folder)
            if not tasks:
                return True

            return self._execute_copy(tasks)

        except Exception as e:
            print(f"Copy failed: {e}")
            return False

    def _validate_source(self) -> None:
        if not self.src_path.exists():
            msg = f"Source path does not exist: {self.src_path}"
            raise FileNotFoundError(msg)
        if not self.src_path.is_dir():
            msg = f"Source must be a directory: {self.src_path}"
            raise NotADirectoryError(msg)

    def _prepare_tasks(self, files: list[Path], dest_folder: Path) -> list[tuple[Path, Path]]:
        tasks = []
        for filepath in files:
            if filepath.is_file():
                relative_path = filepath.relative_to(self.src_path)
                dest_file = dest_folder / relative_path
                tasks.append((filepath, dest_file))
        return tasks

    def _execute_copy(self, tasks: list[tuple[Path, Path]]) -> bool:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        num_workers = 8
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(_copy_file, task) for task in tasks]
            for future in as_completed(futures):
                success, dest_file, error = future.result()
                if not success:
                    print(f"Failed to copy {dest_file}: {error}")
                    return False
        return True


def copy_dir(src: str, dest: str) -> bool:
    copier = _DirectoryCopier(src, dest)
    return copier.copy()


def _move_file(args: tuple[Path, Path]) -> tuple[bool, Path, Exception | None]:
    from shutil import move

    src_file, dest_file = args
    try:
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        move(str(src_file), str(dest_file))
        return (True, dest_file, None)
    except Exception as e:
        return (False, dest_file, e)


class _DirectoryMover:
    def __init__(self, src: str, dest: str):
        self.src_path = Path(src).resolve()
        self.dest_path = Path(dest).resolve()

    def move(self) -> bool:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        from shutil import move

        try:
            self._validate_source()
            dest_folder = self.dest_path / self.src_path.name

            if dest_folder.exists() and any(dest_folder.iterdir()):
                print(f"Warning: Destination {dest_folder} already exists and is not empty")
                return False

            files = _collect_files(self.src_path)
            if not files:
                if self.src_path.exists():
                    move(str(self.src_path), str(dest_folder))
                return True

            tasks = self._prepare_tasks(files, dest_folder)
            if not tasks:
                return self._cleanup_empty_dirs()

            success = self._execute_move(tasks)
            if success:
                self._cleanup_empty_dirs()
            return success

        except Exception as e:
            print(f"Move failed: {e}")
            return False

    def _validate_source(self) -> None:
        if not self.src_path.exists():
            msg = f"Source path does not exist: {self.src_path}"
            raise FileNotFoundError(msg)
        if not self.src_path.is_dir():
            msg = f"Source must be a directory: {self.src_path}"
            raise NotADirectoryError(msg)

    def _prepare_tasks(self, files: list[Path], dest_folder: Path) -> list[tuple[Path, Path]]:
        tasks = []
        for filepath in files:
            if filepath.is_file():
                relative_path = filepath.relative_to(self.src_path)
                dest_file = dest_folder / relative_path
                tasks.append((filepath, dest_file))
        return tasks

    def _execute_move(self, tasks: list[tuple[Path, Path]]) -> bool:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        num_workers = 8
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(_move_file, task) for task in tasks]
            for future in as_completed(futures):
                success, dest_file, error = future.result()
                if not success:
                    print(f"Failed to move {dest_file}: {error}")
                    return False
        return True

    def _cleanup_empty_dirs(self) -> bool:
        for root, dirs, _files in self.src_path.walk(top_down=False):
            for dir_name in dirs:
                dir_path = Path(root) / dir_name
                try:
                    if dir_path.exists() and not any(dir_path.iterdir()):
                        dir_path.rmdir()
                except OSError:
                    pass
        try:
            if self.src_path.exists() and not any(self.src_path.iterdir()):
                self.src_path.rmdir()
        except OSError:
            pass
        return True


def move_dir(src: str, dest: str) -> bool:
    mover = _DirectoryMover(src, dest)
    return mover.move()


@dataclass
class FileWalkerConfig:
    skip_hidden: bool = False
    skip_symlinks: bool = True
    skip_dirs: set[str] = field(default_factory=lambda: {".git", "__pycache__"})
    file_pattern: str | None = None
    exclude_pattern: str | None = "lazy"
    max_depth: int | None = 999
    follow_symlinks: bool = False


class _ConfigurableFileWalker:
    def __init__(
        self,
        path: Path | str,
        config: FileWalkerConfig | None = None,
        file_filter: Callable[[Path], bool] | None = None,
    ):
        self.path = Path(path).resolve()
        self.config = config or FileWalkerConfig()
        self.file_filter = file_filter

    def walk(self) -> Iterator[Path]:
        if not self.path.exists():
            print(f"{YELLOW}⚠ Warning:{RESET} '{self.path}' does not exist, skipping.")
            return

        if self.path.is_file():
            yield from self._yield_single_file()
        elif self.path.is_dir():
            yield from self._yield_directory_files()
        else:
            print(f"{YELLOW}⚠ Warning:{RESET} '{self.path}' is not a file or directory, skipping.")

    def _yield_single_file(self) -> Iterator[Path]:
        if self.config.skip_symlinks and self.path.is_symlink():
            return
        if self.config.skip_hidden and self.path.name.startswith("."):
            return
        if not self._matches_pattern(self.path):
            return
        if self.file_filter and not self.file_filter(self.path):
            return
        yield self.path

    def _yield_directory_files(self) -> Iterator[Path]:
        for file_path in self.path.rglob("*"):
            if not file_path.is_file():
                continue
            if self.config.skip_symlinks and file_path.is_symlink():
                continue
            if self._should_skip_dir(file_path.parent):
                continue
            if self.config.skip_hidden and any(part.startswith(".") for part in file_path.parts):
                continue
            if not self._matches_pattern(file_path):
                continue
            if self.file_filter and not self.file_filter(file_path):
                continue
            yield file_path

    def _should_skip_dir(self, dir_path: Path) -> bool:
        if self.config.max_depth is not None:
            try:
                depth = len(dir_path.relative_to(dir_path.anchor).parts)
                if depth >= self.config.max_depth:
                    return True
            except ValueError:
                pass
        return any(skip in dir_path.parts for skip in self.config.skip_dirs)

    def _matches_pattern(self, file_path: Path) -> bool:
        if self.config.file_pattern and not file_path.match(self.config.file_pattern):
            return False
        return not (self.config.exclude_pattern and file_path.match(self.config.exclude_pattern))


def get_files_iter_config(
    path: Path | str,
    config: FileWalkerConfig | None = None,
    file_filter: Callable[[Path], bool] | None = None,
) -> Iterator[Path]:
    walker = _ConfigurableFileWalker(path, config, file_filter)
    return walker.walk()


@dataclass
class ReportItem:
    path: str
    category: str
    message: str = ""
    details: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: __import__("time").time())


class ReportGenerator:
    def __init__(self, title: str = "Report", width: int = 60):
        self.title = title
        self.width = width
        self.items: list[ReportItem] = []
        self.stats: dict = defaultdict(int)

    def add_item(self, item: ReportItem) -> None:
        self.items.append(item)
        self.stats[item.category] += 1

    def add_stat(self, key: str, value: int) -> None:
        self.stats[key] = value

    def _print_header(self) -> None:
        print(f"\n{BOLD}{CYAN}{'═' * self.width}{RESET}")
        print(f"{BOLD}{CYAN}║{RESET}{self.title.center(self.width - 2)}{BOLD}{CYAN}║{RESET}")
        print(f"{BOLD}{CYAN}{'═' * self.width}{RESET}")

    def _print_category_summary(
        self, category: str, items: list[ReportItem], color: str, symbol: str, show_all: bool = False
    ) -> None:
        if not items:
            return
        print(f"\n{BOLD}{color}{symbol} {category.capitalize()}: {len(items)}{RESET}")
        display_count = len(items) if show_all else min(5, len(items))
        for item in items[:display_count]:
            print(f"  {color}{symbol}{RESET} {item.path}")
            if item.message:
                print(f"    {DIM}{item.message}{RESET}")
        if len(items) > display_count:
            print(f"  {DIM}... and {len(items) - display_count} more{RESET}")

    def print_report(self, show_all: bool = False, sort_by: str = "path") -> None:
        self._print_header()
        self._sort_items(sort_by)
        categories = self._organize_by_category()
        for category, (items, color, symbol) in categories.items():
            if items:
                self._print_category_summary(category, items, color, symbol, show_all)
        self._print_summary()

    def _sort_items(self, sort_by: str) -> None:
        if sort_by == "path":
            self.items.sort(key=lambda x: x.path)
        elif sort_by == "category":
            self.items.sort(key=lambda x: x.category)
        elif sort_by == "time":
            self.items.sort(key=lambda x: x.timestamp)

    def _organize_by_category(self) -> dict[str, tuple[list[ReportItem], str, str]]:
        categories = {
            "success": ([], GREEN, "✓"),
            "binary": ([], YELLOW, "⊘"),
            "warning": ([], YELLOW, "⚠"),
            "error": ([], RED, "✗"),
            "info": ([], CYAN, "ℹ"),
        }
        for item in self.items:
            if item.category in categories:
                categories[item.category][0].append(item)
        return categories

    def _print_summary(self) -> None:
        print(f"\n{BOLD}{CYAN}{'─' * self.width}{RESET}")
        print(f"{BOLD}Summary:{RESET}")
        for key, value in sorted(self.stats.items()):
            if isinstance(value, int):
                print(f"  {key.replace('_', ' ').title():.<30} {BOLD}{value:,}{RESET}")
        print(f"{BOLD}{CYAN}{'─' * self.width}{RESET}\n")

    def export_to_file(self, filepath: Path, format: str = "text") -> None:
        if format == "text":
            self._export_text(filepath)
        elif format == "csv":
            self._export_csv(filepath)

    def _export_text(self, filepath: Path) -> None:
        with open(filepath, "w") as f:
            f.write(f"{self.title}\n{'=' * self.width}\n")
            for item in self.items:
                f.write(f"[{item.category.upper()}] {item.path}")
                if item.message:
                    f.write(f" - {item.message}")
                f.write("\n")
            f.write(f"\nSummary:\n")
            f.writelines(f"  {key}: {value}\n" for key, value in self.stats.items())

    def _export_csv(self, filepath: Path) -> None:
        import csv
        import datetime

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Path", "Category", "Message", "Timestamp"])
            for item in self.items:
                writer.writerow([
                    item.path,
                    item.category,
                    item.message,
                    datetime.datetime.fromtimestamp(item.timestamp).isoformat(),
                ])


def remove_blank_lines(text: str) -> str:
    lines = text.splitlines(keepends=True)
    result_lines = []
    prev_blank = False
    for line in lines:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        result_lines.append(line)
        prev_blank = is_blank
    return "".join(result_lines)


class _PythonFileChecker:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def is_python_file(self) -> bool:
        if is_binary(self.path):
            return False
        if not self.path.stat().st_size:
            return False
        if self.path.is_file() and self.path.suffix == ".py":
            return True
        if not self.path.suffix:
            return self._check_shebang_or_parse()
        return False

    def _check_shebang_or_parse(self) -> bool:
        from ast import parse as ast_parse

        with self.path.open("rb") as f:
            first_two = f.read(2)
            if first_two == b"#!":
                f.seek(0)
                first100 = f.read(100)
                if b"python" in first100:
                    return True

            try:
                f.seek(0)
                code = f.read().decode("utf-8")
                ast_parse(code)
                return True
            except Exception:
                return False


def is_python_file(path: str | Path) -> bool:
    checker = _PythonFileChecker(path)
    return checker.is_python_file()


class _PythonFileFinder:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.pyfiles: list[Path] = []

    def find(self) -> list[Path]:
        if self.path.is_file():
            return self._handle_single_file()
        if not self.path.is_dir():
            return []
        return self._walk_directory()

    def _handle_single_file(self) -> list[Path]:
        if self.path.suffix == ".py":
            return [self.path]
        if not self.path.suffix and not self.path.name.startswith(".") and is_python_file(self.path):
            return [self.path]
        return []

    def _walk_directory(self) -> list[Path]:
        stack: list[Path] = [self.path]
        while stack:
            current = stack.pop()
            try:
                with os_scandir(current) as entries:
                    self._process_dir_entries(entries, stack)
            except (PermissionError, OSError):
                continue
        return sorted(self.pyfiles)

    def _process_dir_entries(self, entries, stack: list[Path]) -> None:
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in SKIP_DIRS:
                    stack.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                p = Path(entry.path)
                if p.suffix == ".py" or (not p.suffix and not p.name.startswith(".") and is_python_file(p)):
                    self.pyfiles.append(p)


def get_pyfiles(path: str | Path) -> list[Path]:
    finder = _PythonFileFinder(path)
    return finder.find()


class _PathWalker:
    def __init__(self, inputs: str | Path | list[str | Path], ext: list[str] | None = None):
        self.inputs = inputs if isinstance(inputs, list) else [inputs]
        self.ext = ext

    def walk(self) -> Iterator[Path]:
        for inp in self.inputs:
            inp = Path(inp)
            if inp.is_file():
                if self.ext is None or inp.suffix in self.ext:
                    yield inp
            elif inp.is_dir():
                yield from get_fast(inp, self.ext)
            else:
                yield from self._handle_glob_pattern(inp)

    def _handle_glob_pattern(self, inp: Path) -> Iterator[Path]:
        parent = inp.parent if "*" in inp.name else inp
        pattern = inp.name if "*" in inp.name else str(inp)
        for match in parent.glob(pattern):
            if match.is_file():
                if self.ext is None or match.suffix in self.ext:
                    yield match
            elif match.is_dir():
                yield from get_fast(match, self.ext)


def walk_paths(inputs: str | Path | list[str | Path], ext: list[str] | None = None) -> Iterator[Path]:
    walker = _PathWalker(inputs, ext)
    return walker.walk()


def worker(file_path: Path, process_fn: Callable[[Path], Any]) -> tuple[Path, Any]:
    try:
        result = process_fn(file_path)
        return (file_path, result)
    except Exception as e:
        return (file_path, f"ERROR: {e}")


class _FileProcessor:
    def __init__(
        self, file_iter: Iterator[Path], process_fn: Callable[[Path], Any], max_workers: int = 4, prefetch: int = 128
    ):
        self.file_iter = file_iter
        self.process_fn = process_fn
        self.max_workers = max_workers
        self.prefetch = prefetch

    def process(self) -> Iterator[tuple[Path, Any]]:
        ctx = get_context("spawn")
        with ctx.Pool(processes=self.max_workers) as pool:
            worker_fn = functools.partial(worker, process_fn=self.process_fn)
            batch = []
            for file_path in self.file_iter:
                batch.append(file_path)
                if len(batch) >= self.prefetch:
                    yield from pool.imap_unordered(worker_fn, batch)
                    batch = []
            for result in pool.imap_unordered(worker_fn, batch):
                yield result


def process_files(
    file_iter: Iterator[Path], process_fn: Callable[[Path], Any], max_workers: int = 4, prefetch: int = 128
) -> Iterator[tuple[Path, Any]]:
    processor = _FileProcessor(file_iter, process_fn, max_workers, prefetch)
    return processor.process()


def main_func(
    inputs: str | Path | list[str | Path],
    process_fn: Callable[[Path], Any],
    ext: list[str] | None = None,
    max_workers: int = 8,
    prefetch: int = 128,
    verbose: bool = True,
) -> None:
    file_iter = walk_paths(inputs, ext)
    count = 0
    errors = 0
    for file_path, result in process_files(file_iter, process_fn, max_workers, prefetch):
        count += 1
        if verbose:
            status = "✓" if not str(result).startswith("ERROR") else "✗"
            print(f"{status} {file_path}: {result}")
        if str(result).startswith("ERROR"):
            errors += 1
    if verbose:
        print(f"\n{count} files processed, {errors} errors")


class _TextFileDeterminer:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._validate()

    def _validate(self) -> None:
        if not self.path.exists():
            msg = f"File not found: {self.path}"
            raise FileNotFoundError(msg)
        if not self.path.is_file():
            msg = f"Path is not a file: {self.path}"
            raise ValueError(msg)

    def is_text(self) -> bool:
        if self.path.suffix in BIN_EXT:
            return False
        if self.path.suffix in TXT_EXT:
            return True
        try:
            with open(self.path, "rb") as f:
                chunk = f.read()
            return not _check_binary_chunk(chunk)
        except Exception as e:
            msg = f"Error checking file {self.path}: {e!s}"
            raise RuntimeError(msg)


def is_text_file(path: str | Path) -> bool:
    determiner = _TextFileDeterminer(path)
    return determiner.is_text()


def _check_binary_chunk(chunk: bytes) -> bool:
    if not chunk:
        return False

    null_count = chunk.count(b"\x00")
    if len(chunk) < 100:
        null_ratio = null_count / len(chunk)
        if null_ratio > 0.1:
            return True
    else:
        null_ratio = null_count / len(chunk)
        if null_ratio > 0.05:
            return True

    printable_chars = sum(1 for byte in chunk if 32 <= byte <= 126)
    total_chars = len(chunk)
    if total_chars > 0 and (printable_chars / total_chars) < 0.7:
        return True

    return bool(len(chunk) > 100 and null_count > 0 and printable_chars / total_chars < 0.5)


def atomic_write(path: Path, content: str) -> None:
    from os import replace as os_replace

    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    try:
        os_replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def walk_files(path: str | Path, ext: list[str] | None = None) -> list[Path]:
    files = []
    for root, dirs, filenames in Path(path).walk(top_down=True, on_error=None):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in filenames:
            item = root / name
            if item.is_symlink():
                continue
            if ext is None or item.suffix in ext:
                files.append(item)
    return files


def walkfiles(path: str | Path, ext: list[str] | None = None) -> Iterator[Path]:
    for root, dirs, filenames in Path(path).walk(top_down=True, on_error=None):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in filenames:
            item = root / name
            if item.is_symlink():
                continue
            if ext is None or item.suffix in ext:
                yield item


class _SizeByExtensionCalculator:
    def __init__(self, root_dir: str | Path = ".", ext: list[str] | None = None):
        self.root_path = Path(root_dir)
        self.normalized_exts = {e.lower() for e in ext} if ext is not None else None

    def calculate(self) -> int:
        total_size_bytes = 0
        for file_path in self.root_path.rglob("*"):
            if file_path.is_symlink():
                continue
            if file_path.is_file():
                if self.normalized_exts is not None and file_path.suffix.lower() not in self.normalized_exts:
                    continue
                try:
                    total_size_bytes += file_path.stat().st_size
                except (PermissionError, FileNotFoundError):
                    continue
        return total_size_bytes


def gsze(root_dir: str | Path = ".", ext: list[str] | None = None) -> int:
    calculator = _SizeByExtensionCalculator(root_dir, ext)
    return calculator.calculate()
