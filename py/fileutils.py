from __future__ import annotations

import contextlib
import functools
from collections import defaultdict
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from multiprocessing import get_context
from os import scandir as os_scandir
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Optional, overload

from .const import (
    BIN_EXT,
    CHUNK_SIZE,
    EMULATED,
    IMGEXT,
    PY_KEYWORDS,
    SDCARD,
    SKIP_DIRS,
    THRESHOLD,
    TXT_EXT,
    ZERO_DOT_THREE,
)
from .isbinary import is_binary


@overload
def get_file_age(path: str | Path, str_mode: bool = False) -> float: ...
@overload
def get_file_age(path: str | Path, str_mode: bool = True) -> str: ...


def read_lines(path: str | Path, ke: bool = True) -> list[str]:
    path = Path(path)
    if path.stat().st_size > THRESHOLD:
        return read_lines_mmap(path, ke)
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=ke)
    if not lines[-1].endswith(("\n", "\r\n", "\r")) and data.endswith(b"\n"):
        lines.append("")
    return lines


def read_lines_mmap(path: Path, keep_ends: bool = True) -> list[str]:
    import mmap

    size = path.stat().st_size
    with path.open("rb") as f, mmap.mmap(f.fileno(), size, access=mmap.ACCESS_READ) as mm:
        text = mm[:].decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=keep_ends)
    if not lines[-1].endswith(("\n", "\r\n", "\r")) and size > 0 and text.endswith("\n"):
        lines.append("")
    return lines


def gext(path: str | Path) -> str:
    path = Path(path)
    suffs = path.suffixes
    if not suffs:
        return ""
    multipart_prefixes = frozenset({".tar", ".min", ".bundle", ".log", ".spec", ".test", ".d", ".module"})
    if len(suffs) > 1:
        if suffs[0] in multipart_prefixes:
            return "".join(suffs)
        if suffs[-1] in {".gz", ".xz", ".bz2", ".zst", ".lz"} and suffs[-2] == ".tar":
            return f".tar{suffs[-1]}"
        return suffs[-1]
    return suffs[0]


def get_dirs(path: str | Path) -> list[Path]:
    path = Path(path)
    if not path.is_dir():
        return []
    dirs = []
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os_scandir(current) as entries:
                subdirs = [Path(entry.path) for entry in entries if entry.is_dir(follow_symlinks=False)]
                dirs.extend(subdirs)
                stack.extend(subdirs)
        except (PermissionError, OSError):
            continue
    return dirs


def get_file_age(path: str | Path, str_mode: bool = False) -> float | str:
    from os import stat as os_stat
    from time import time as time_time

    path = Path(path)
    if not path.exists():
        return 0.0 if not str_mode else "0 sec"
    if not path.is_file():
        return -1.0 if not str_mode else "0 sec"
    current_time = time_time()
    file_stat = os_stat(path)
    age = current_time - file_stat.st_ctime
    if not str_mode:
        return age
    int_age = int(age)
    if int_age < 0:
        return "0 sec"
    units = (
        ("y", 365 * 24 * 60 * 60),
        ("m", 30 * 24 * 60 * 60),
        ("d", 24 * 60 * 60),
        ("h", 60 * 60),
        ("min", 60),
        ("sec", 1),
    )
    parts = []
    for name, seconds_per_unit in units:
        value, int_age = divmod(int_age, seconds_per_unit)
        if value:
            parts.append(f"{value} {name}")
    return ", ".join(parts) if parts else "0 sec"


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


def normalize_filename(path: str | Path) -> str:
    from re import compile as re_compile, escape as re_escape

    path = str(path)
    special_characters = '<>:"/\\|?*' + "".join(map(chr, range(32)))
    pattern = re_compile("|".join(map(re_escape, special_characters)))
    return pattern.sub("_", path)


def normalize_path(path: str | Path) -> Path:
    pathstr = str(path)
    if EMULATED in pathstr:
        return Path(pathstr.replace(EMULATED, SDCARD))
    return Path(path).resolve()


def reverse_dict(input_dict: dict) -> dict:
    from collections import defaultdict

    seenkeys = set()
    seenvals = set()
    has_rep: bool = False
    rev = defaultdict(list)
    for k, v in input_dict.items():
        if k not in seenkeys:
            seenkeys.add(k)
        else:
            has_rep = True
        if v not in seenvals:
            seenvals.add(v)
        else:
            has_rep = True
        if not has_rep:
            rev[v] = k
        else:
            rev[v].append(k)
    return dict(rev)


def fsz(sz: float) -> str:
    sz = abs(int(sz))
    if sz == 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    i = min((int(sz).bit_length() - 1) // 10, len(units) - 1)
    value = sz / 1024**i
    if i == 0:
        return f"{int(value)} {units[i]}"
    return f"{value:.1f} {units[i]}"


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


def unique_path(path: Path | str) -> Path:
    path = _clean_fname(Path(path))
    if not path.exists():
        return path
    parent = path.parent
    suffixes = path.suffixes
    if suffixes:
        first_suffix_index = path.name.find(suffixes[0])
        stem = path.name[:first_suffix_index]
        full_suffix = "".join(suffixes)
    else:
        stem = path.name
        full_suffix = ""
    counter = 1
    while True:
        new_path = parent / f"{stem}_{counter}{full_suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def _clean_fname(path: Path) -> Path:
    from re import sub as re_sub

    clean_name = re_sub(r"(_\d+)+", "", path.name)
    return path.with_name(clean_name)


def format_time(t: float) -> str:
    if t <= 0:
        return "0s"
    if t < 1:
        ms = t * 1000
        if ms < 1:
            return f"{ms * 1000:.0f}µs"
        return f"{ms:.2f}ms"
    if t < 60:
        return f"{t:.0f}s"
    if t < 3600:
        minutes = int(t // 60)
        secs = int(t % 60)
        return f"{minutes}m" + (f", {secs}s" if secs else "")
    if t < 86400:
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
    if t < 86400 * 30:
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
    months = t / (86400 * 30)
    if months < 1:
        return "less than 1 month"
    return f"{months:.2f} months"


def runcmd(
    cmd: list[str], run_silently: bool = False, show_output: bool = True, timeout: float | None = None
) -> tuple[int, str, str]:
    from subprocess import DEVNULL as _DEVNULL, TimeoutExpired as subprocess_TimeoutExpired, run as subprocess_run
    from sys import stderr as sys_stderr, stdout as sys_stdout

    if not cmd:
        raise ValueError("cmd must be a non-empty list (e.g., ['ls', '-l'])")
    try:
        if run_silently:
            result = subprocess_run(cmd, stdout=_DEVNULL, stderr=_DEVNULL, timeout=timeout)
            return (result.returncode, "", "")
        result = subprocess_run(cmd, capture_output=True, text=True, timeout=timeout)
        stdout, stderr = (result.stdout, result.stderr)
        if show_output:
            if stdout:
                sys_stdout.write(stdout)
                sys_stdout.flush()
            if stderr:
                sys_stderr.write(stderr)
                sys_stderr.flush()
        return (result.returncode, stdout, stderr)
    except FileNotFoundError:
        msg = f"Command not found: '{cmd[0]}'"
        if show_output and (not run_silently):
            print(msg, file=sys_stderr)
        return (127, "", msg)
    except PermissionError:
        msg = f"Permission denied: '{cmd[0]}'"
        if show_output and (not run_silently):
            print(msg, file=sys_stderr)
        return (126, "", msg)
    except subprocess_TimeoutExpired:
        msg = f"Command timed out after {timeout}s: {' '.join(cmd)}"
        if show_output and (not run_silently):
            print(msg, file=sys_stderr)
        return (124, "", msg)
    except Exception as e:
        msg = f"Unexpected error running '{cmd[0]}': {e}"
        if show_output and (not run_silently):
            print(msg, file=sys_stderr)
        return (1, "", msg)


def write_txt_file(path: str | Path, data: str, overwrite: bool = False) -> bool:
    if not isinstance(data, str):
        return False
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and (not overwrite):
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


def rrs(path, before: int, after: int) -> None:
    saved = before - after
    if not saved:
        msg = "\x1b[5;92mNO CHANGE\x1b[0m"
    else:
        ratio = (1 - (after / before)) * 100
        sign = "+" if saved > 0 else "-"
        msg = f"\x1b[5;92m{before}->{after} = {sign} \x1b[5;94m{fsz(saved)}\x1b[0m | \x1b[5;96m{ratio:.1f}\x1b[5;91m%\x1b[0m"
    print(f"{path.name}|{msg}\n")


def is_empty(path: str | Path) -> bool:
    path = Path(path)
    return path.is_dir() and (not any(path.iterdir()))


def get_files_scandir(path: str | Path, include_hidden: bool = True, ext: list[str] | None = None) -> list[Path]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")
    ext_tuple = tuple(ext) if ext else None
    files = []
    stack = [path]
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
        raise NotADirectoryError(f"Path is not a directory: {directory}")
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


def get_files(path: str | Path, ext: list[str] | None = None) -> list[Path]:
    from collections import deque

    path = Path(path)
    queue = deque([path])
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
            elif item.is_file() and (ext is None or item.suffix in ext):
                files.append(item)
    return sorted(files)


def getfiles(root_dir: str | Path, ext: list[str] | None = None) -> list[Path]:
    from fastwalk import walk_files

    files = []
    for path in walk_files(root_dir):
        if should_skip(path):
            continue
        if path.is_file():
            if ext is None or (path.suffix and path.suffix in ext):
                files.append(path)
            else:
                files.append(path)
    return sorted(files)


def get_files_pathlib(path: Path, include_hidden: bool = True, ext: list[str] | None = None) -> list[Path]:
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")
    files: list[Path] = []
    stack = [path]
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
    from os import scandir as os_scandir

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")
    ext_tuple = tuple(ext) if ext is not None else None
    files = []
    stack = [path]
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


def gsz(path: str | Path) -> int | float:
    if not isinstance(path, (Path, str)):
        return 0
    p = Path(path)
    if p.is_symlink():
        return 0
    if p.is_file():
        return p.stat().st_size
    if p.is_dir():
        return _dir_size(p)
    return 0


def _dir_size(path: Path) -> int:
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
                futures.append(executor.submit(_dir_size, item))
        for future in futures:
            total += future.result()
    return total


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


def copy_dir(src: str, dest: str) -> bool:
    from concurrent.futures import ProcessPoolExecutor, as_completed

    try:
        src_path = Path(src).resolve()
        dest_path = Path(dest).resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {src_path}")
        if not src_path.is_dir():
            raise NotADirectoryError(f"Source must be a directory: {src_path}")
        dest_folder = dest_path / src_path.name
        dest_folder.mkdir(parents=True, exist_ok=True)
        files = _collect_files(src_path)
        if not files:
            return True
        tasks = []
        for filepath in files:
            if filepath.is_file():
                relative_path = filepath.relative_to(src_path)
                dest_file = dest_folder / relative_path
                tasks.append((filepath, dest_file))
        if not tasks:
            return True
        num_workers = 8
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(_copy_file, task) for task in tasks]
            for future in as_completed(futures):
                success, dest_file, error = future.result()
                if not success:
                    print(f"Failed to copy {dest_file}: {error}")
                    return False
        return True
    except Exception as e:
        print(f"Copy failed: {e}")
        return False


def _move_file(args: tuple[Path, Path]) -> tuple[bool, Path, Exception | None]:
    from shutil import move

    src_file, dest_file = args
    try:
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        move(str(src_file), str(dest_file))
        return (True, dest_file, None)
    except Exception as e:
        return (False, dest_file, e)


def move_dir(src: str, dest: str) -> bool:
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from shutil import move

    try:
        src_path = Path(src).resolve()
        dest_path = Path(dest).resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {src_path}")
        if not src_path.is_dir():
            raise NotADirectoryError(f"Source must be a directory: {src_path}")
        dest_folder = dest_path / src_path.name
        if dest_folder.exists() and any(dest_folder.iterdir()):
            print(f"Warning: Destination {dest_folder} already exists and is not empty")
            return False
        files = _collect_files(src_path)
        if not files:
            if src_path.exists():
                move(str(src_path), str(dest_folder))
            return True
        tasks = []
        for filepath in files:
            if filepath.is_file():
                relative_path = filepath.relative_to(src_path)
                dest_file = dest_folder / relative_path
                tasks.append((filepath, dest_file))
        if not tasks:
            for item in src_path.rglob("*"):
                if item.is_dir():
                    relative_path = item.relative_to(src_path)
                    dest_dir = dest_folder / relative_path
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    if item.exists():
                        with contextlib.suppress(OSError):
                            item.rmdir()
            if src_path.exists():
                with contextlib.suppress(OSError):
                    src_path.rmdir()
            return True
        num_workers = 8
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(_move_file, task) for task in tasks]
            for future in as_completed(futures):
                success, dest_file, error = future.result()
                if not success:
                    print(f"Failed to move {dest_file}: {error}")
                    return False
        for root, dirs, _files in src_path.walk(topdown=False):
            for dir_name in dirs:
                dir_path = Path(root) / dir_name
                try:
                    if dir_path.exists() and (not any(dir_path.iterdir())):
                        dir_path.rmdir()
                except OSError:
                    pass
        try:
            if src_path.exists() and (not any(src_path.iterdir())):
                src_path.rmdir()
        except OSError:
            pass
        return True
    except Exception as e:
        print(f"Move failed: {e}")
        return False


BOLD = "\x1b[1m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[36m"
RED = "\x1b[31m"
RESET = "\x1b[0m"
DIM = "\x1b[2m"


@dataclass
class FileWalkerConfig:
    skip_hidden: bool = False
    skip_symlinks: bool = True
    skip_dirs: set[str] = field(
        default_factory=lambda: {
            ".git",
            "__pycache__",
        }
    )
    file_pattern: str | None = None
    exclude_pattern: str | None = "lazy"
    max_depth: int | None = 999
    follow_symlinks: bool = False


def get_files_iter_config(
    path: Path | str,
    config: FileWalkerConfig | None = None,
    file_filter: Callable[[Path], bool] | None = None,
) -> Iterator[tuple[Path, Path]]:
    config = config or FileWalkerConfig()

    def should_skip_dir(dir_path: Path) -> bool:
        if config.max_depth is not None:
            try:
                depth = len(dir_path.relative_to(dir_path.anchor).parts)
                if depth >= config.max_depth:
                    return True
            except ValueError:
                pass
        return any(skip in dir_path.parts for skip in config.skip_dirs)

    def matches_pattern(file_path: Path) -> bool:
        if config.file_pattern and not file_path.match(config.file_pattern):
            return False
        return not (config.exclude_pattern and file_path.match(config.exclude_pattern))

    path = Path(path).resolve()
    if not path.exists():
        print(f"{YELLOW}⚠ Warning:{RESET} '{path}' does not exist, skipping.")
        return []
    if path.is_file():
        if config.skip_symlinks and path.is_symlink():
            return []
        if config.skip_hidden and path.name.startswith("."):
            return []
        if not matches_pattern(path):
            return []
        if file_filter and not file_filter(path):
            return []
        yield path
    elif path.is_dir():
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            if config.skip_symlinks and file_path.is_symlink():
                continue
            if should_skip_dir(file_path.parent):
                continue
            if config.skip_hidden and any(part.startswith(".") for part in file_path.parts):
                continue
            if not matches_pattern(file_path):
                continue
            if file_filter and not file_filter(file_path):
                continue
            yield file_path
    else:
        print(f"{YELLOW}⚠ Warning:{RESET} '{path}' is not a file or directory, skipping.")


@dataclass
class ReportItem:
    import time

    path: str
    category: str
    message: str = ""
    details: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class ReportGenerator:
    def __init__(self, title: str = "Report", width: int = 60):
        self.title = title
        self.width = width
        self.items: list[ReportItem] = []
        self.stats: dict = defaultdict(int)

    def add_item(self, item: ReportItem):
        self.items.append(item)
        self.stats[item.category] += 1

    def add_stat(self, key: str, value: int):
        self.stats[key] = value

    def _print_header(self):
        print(f"\n{BOLD}{CYAN}{'═' * self.width}{RESET}")
        print(f"{BOLD}{CYAN}║{RESET}{self.title.center(self.width - 2)}{BOLD}{CYAN}║{RESET}")
        print(f"{BOLD}{CYAN}{'═' * self.width}{RESET}")

    def _print_category_summary(
        self, category: str, items: list[ReportItem], color: str, symbol: str, show_all: bool = False
    ):
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

    def print_report(self, show_all: bool = False, sort_by: str = "path"):
        self._print_header()
        if sort_by == "path":
            self.items.sort(key=lambda x: x.path)
        elif sort_by == "category":
            self.items.sort(key=lambda x: x.category)
        elif sort_by == "time":
            self.items.sort(key=lambda x: x.timestamp)
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
        for category, (items, color, symbol) in categories.items():
            if items:
                self._print_category_summary(category, items, color, symbol, show_all)
        self._print_summary()

    def _print_summary(self):
        print(f"\n{BOLD}{CYAN}{'─' * self.width}{RESET}")
        print(f"{BOLD}Summary:{RESET}")
        for key, value in sorted(self.stats.items()):
            if isinstance(value, int):
                print(f"  {key.replace('_', ' ').title():.<30} {BOLD}{value:,}{RESET}")
        print(f"{BOLD}{CYAN}{'─' * self.width}{RESET}\n")

    def export_to_file(self, filepath: Path, format: str = "text"):
        import datetime

        if format == "text":
            with open(filepath, "w") as f:
                f.write(f"{self.title}\n{'=' * self.width}\n")
                for item in self.items:
                    f.write(f"[{item.category.upper()}] {item.path}")
                    if item.message:
                        f.write(f" - {item.message}")
                    f.write("\n")
                f.write(f"\nSummary:\n")
                f.writelines(f"  {key}: {value}\n" for key, value in self.stats.items())
        elif format == "csv":
            import csv

            with open(filepath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Path", "Category", "Message", "Timestamp"])
                for item in self.items:
                    writer.writerow(
                        [item.path, item.category, item.message, datetime.fromtimestamp(item.timestamp).isoformat()]
                    )


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


def is_python_file(path: str | Path) -> bool:
    from ast import parse as ast_parse

    path = Path(path)
    if is_binary(path):
        return False
    if not path.stat().st_size:
        return False
    if path.is_file() and path.suffix == ".py":
        return True
    if not path.suffix:
        with path.open("rb") as f:
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
            except:
                return False
    return False


def get_pyfiles(path: str | Path) -> list[Path]:
    path = Path(path)
    if path.is_file():
        if path.suffix == ".py":
            return [path]
        if not path.suffix and (not path.name.startswith(".")) and is_python_file(path):
            return [path]
        return []
    if not path.is_dir():
        return []
    pyfiles = []
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os_scandir(current) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in SKIP_DIRS:
                            stack.append(entry)
                    elif entry.is_file(follow_symlinks=False):
                        p = Path(entry.path)
                        if p.suffix == ".py" or (not p.suffix and (not p.name.startswith(".")) and is_python_file(p)):
                            pyfiles.append(p)
        except (PermissionError, OSError):
            continue
    return sorted(pyfiles)


def walk_paths(inputs: str | Path | list[str | Path], ext: list[str] | None = None) -> Iterator[Path]:
    if isinstance(inputs, (str, Path)):
        inputs = [inputs]
    for inp in inputs:
        inp = Path(inp)
        if inp.is_file():
            if ext is None or inp.suffix in ext:
                yield inp
        elif inp.is_dir():
            yield from get_fast(inp, ext)
        else:
            parent = inp.parent if "*" in inp.name else inp
            pattern = inp.name if "*" in inp.name else str(inp)
            for match in parent.glob(pattern):
                if match.is_file():
                    if ext is None or match.suffix in ext:
                        yield match
                elif match.is_dir():
                    yield from get_fast(match, ext)


def worker(file_path: Path, process_fn: Callable[[Path], Any]) -> tuple[Path, Any]:
    try:
        result = process_fn(file_path)
        return (file_path, result)
    except Exception as e:
        return (file_path, f"ERROR: {e}")


def process_files(
    file_iter: Iterator[Path], process_fn: Callable[[Path], Any], max_workers: int = 4, prefetch: int = 128
) -> Iterator[tuple[Path, Any]]:
    ctx = get_context("spawn")
    with ctx.Pool(processes=max_workers) as pool:
        worker_fn = functools.partial(worker, process_fn=process_fn)
        batch = []
        for file_path in file_iter:
            batch.append(file_path)
            if len(batch) >= prefetch:
                for result in pool.imap_unordered(worker_fn, batch):
                    yield result
                batch = []
        for result in pool.imap_unordered(worker_fn, batch):
            yield result


def main_func(
    inputs: str | Path | list[str | Path],
    process_fn: Callable[[Path], Any],
    ext: list[str] | None = None,
    max_workers: int = 8,
    prefetch: int = 128,
    verbose: bool = True,
):
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


def is_text_file(path: str | Path) -> bool:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Path is not a file: {path}")
    if path.suffix in BIN_EXT:
        return False
    if path.suffix in TXT_EXT:
        return True
    try:
        with open(path, "rb") as f:
            chunk = f.read()
        size = path.stat().st_size
        return not _check_binary_chunk(chunk)
    except Exception as e:
        raise RuntimeError(f"Error checking file {path}: {e!s}")


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


def walkfiles(path: str | Path, ext: list[str] | None = None):
    for root, dirs, filenames in Path(path).walk(top_down=True, on_error=None):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in filenames:
            item = root / name
            if item.is_symlink():
                continue
            if ext is None or item.suffix in ext:
                yield item
