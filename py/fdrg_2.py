from __future__ import annotations

import argparse
import fnmatch
import tarfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from queue import Queue

from fastwalk import walk_files

pause_event = threading.Event()
pause_event.set()
results_queue = Queue()
DEFAULT_EXCLUDED_DIRS = {".git"}
DEFAULT_SKIPPED_EXTS = {".pyc", ".bak"}
ARCHIVE_EXTENSIONS = (
    ".tar.gz",
    ".tar",
    ".tar.xz",
    ".tar.zst",
    ".tar.bz2",
    ".zip",
    ".whl",
    ".apk",
)


def setup_keyboard_listener() -> bool:
    try:
        import keyboard

        def on_key_press(event) -> None:
            if event.name in {"space", "p"} and pause_event.is_set():
                pause_event.clear()
                print("\n[PAUSED] Press 'c' to continue...")
            elif event.name == "c" and not pause_event.is_set():
                pause_event.set()
                print("\n[RESUMED] Searching...")

        keyboard.on_press(on_key_press)
        return True
    except ImportError:
        print("Warning: 'keyboard' not installed. Pause disabled.")
        return False


def is_excluded(path: Path, excluded_dirs, excluded_patterns) -> bool:
    for part in path.parts:
        if part in excluded_dirs:
            return True
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in excluded_patterns)


def should_skip_file(path: Path) -> bool:
    return path.suffix in DEFAULT_SKIPPED_EXTS


def report_result(file_path, line_num=None) -> None:
    if line_num:
        print(f"[FOUND] {file_path} (Line: {line_num})")
    else:
        print(f"[FOUND] {file_path}")
    results_queue.put((file_path, line_num))


def search_in_file(file_path: Path, search_string, search_content):
    pause_event.wait()
    results = []
    if not search_content:
        if search_string.lower() in file_path.name.lower():
            results.append((str(file_path), None))
        return results
    try:
        with Path(file_path).open(encoding="utf-8", errors="ignore") as f:
            for ln, line in enumerate(f, 1):
                pause_event.wait()
                if search_string in line:
                    results.append((str(file_path), ln))
    except Exception:
        pass
    return results


def extract_and_search_archive(archive_path: Path, search_string, search_content):
    results = []
    try:
        if archive_path.suffix == ".zip" or archive_path.name.endswith((".whl", ".apk")):
            with zipfile.ZipFile(archive_path) as zf:
                for member in zf.namelist():
                    pause_event.wait()
                    ref = f"{archive_path}::{member}"
                    if not search_content:
                        if search_string.lower() in member.lower():
                            results.append((ref, None))
                    else:
                        try:
                            content = zf.read(member).decode("utf-8", errors="ignore")
                            for ln, line in enumerate(content.splitlines(), 1):
                                if search_string in line:
                                    results.append((ref, ln))
                        except Exception:
                            pass
        else:
            with tarfile.open(archive_path, "r:*") as tf:
                for m in tf.getmembers():
                    pause_event.wait()
                    if not m.isfile():
                        continue
                    ref = f"{archive_path}::{m.name}"
                    if not search_content:
                        if search_string.lower() in m.name.lower():
                            results.append((ref, None))
                    else:
                        try:
                            f = tf.extractfile(m)
                            if f:
                                content = f.read().decode("utf-8", errors="ignore")
                                for ln, line in enumerate(content.splitlines(), 1):
                                    if search_string in line:
                                        results.append((ref, ln))
                        except Exception:
                            pass
    except Exception:
        pass
    return results


def process_file(path: Path, search_string, search_content) -> None:
    path = Path(path)
    if path.name.endswith(ARCHIVE_EXTENSIONS):
        results = extract_and_search_archive(path, search_string, search_content)
    else:
        results = search_in_file(path, search_string, search_content)
    for r in results:
        report_result(*r)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fast recursive string search")
    parser.add_argument("search_string")
    parser.add_argument("-c", "--content", action="store_true")
    parser.add_argument("-d", "--directory", default=".")
    parser.add_argument("-o", "--output", default="output")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude dir or glob (repeatable)",
    )
    args = parser.parse_args()
    excluded_dirs = DEFAULT_EXCLUDED_DIRS | {e for e in args.exclude if not any(ch in e for ch in "*?[]")}
    excluded_patterns = {e for e in args.exclude if any(ch in e for ch in "*?[]")}
    setup_keyboard_listener()
    root = Path(args.directory).resolve()
    print(f"[INFO] Root: {root}")
    print(f"[INFO] Mode: {'content' if args.content else 'filename'}")
    print(f"[INFO] Excluded dirs: {sorted(excluded_dirs)}")
    print(f"[INFO] Excluded patterns: {sorted(excluded_patterns)}")
    print("-" * 40)
    files = []
    for pth in walk_files(root):
        path = Path(pth)
        if path.is_dir():
            continue
        if should_skip_file(path):
            continue
        if is_excluded(path, excluded_dirs, excluded_patterns):
            continue
        files.append(path)
    print(f"[INFO] Files queued: {len(files)}\n")
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(process_file, p, args.search_string, args.content) for p in files]
        for _f in as_completed(futures):
            pass
    print(f"[INFO] Total results: {results_queue.qsize()}")


if __name__ == "__main__":
    raise SystemExit(main())
