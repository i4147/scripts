import argparse
import fnmatch
import tarfile
import threading
import zipfile
from collections.abc import Sequence
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from fastwalk import walk_files
from loguru import logger

pause_event = threading.Event()
pause_event.set()
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
WORKER_COUNT = 8
SearchResult = tuple[str, int | None]


def setup_keyboard_listener():
    try:
        import keyboard

        def on_key_press(event):
            if event.name in {"space", "p"} and pause_event.is_set():
                pause_event.clear()
                print("PAUSED - press 'c' to continue...")
            elif event.name == "c" and not pause_event.is_set():
                pause_event.set()
                print("RESUMED - searching...")

        keyboard.on_press(on_key_press)
        return True
    except ImportError:
        logger.warning("'keyboard' not installed. Pause disabled.")
        return False


def is_excluded(
    path,
    excluded_dirs,
    excluded_patterns,
):
    for part in path.parts:
        if part in excluded_dirs:
            return True
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in excluded_patterns)


def should_skip_file(path):
    return path.suffix in DEFAULT_SKIPPED_EXTS


def search_in_file(
    path,
    search_string,
    search_content,
):
    pause_event.wait()
    results = []
    if not search_content:
        if search_string.lower() in path.name.lower():
            results.append((str(path), None))
        return results
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for ln, line in enumerate(f, 1):
                pause_event.wait()
                if search_string in line:
                    results.append((str(path), ln))
    except Exception:
        pass
    return results


def extract_and_search_archive(
    archive_path,
    search_string,
    search_content,
):
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


def process_file(
    path,
    search_string,
    search_content,
):
    path = Path(path)
    if path.name.endswith(ARCHIVE_EXTENSIONS):
        return extract_and_search_archive(path, search_string, search_content)
    return search_in_file(path, search_string, search_content)


def collect_files(
    root,
    excluded_dirs,
    excluded_patterns,
):
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
    return files


def _report(results):
    for path, line_num in results:
        if line_num is not None:
            print(f"[FOUND] {path} (Line: {line_num})")
        else:
            print(f"[FOUND] {path}")
    return len(results)


def parse_args(argv=None):
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
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    excluded_dirs = DEFAULT_EXCLUDED_DIRS | {e for e in args.exclude if not any(ch in e for ch in "*?[]")}
    excluded_patterns = {e for e in args.exclude if any(ch in e for ch in "*?[]")}
    setup_keyboard_listener()
    root = Path(args.directory).resolve()
    print(f"Root: {root}")
    print(f"Mode: {'content' if args.content else 'filename'}")
    print(f"Excluded dirs: {sorted(excluded_dirs)}")
    print(f"Excluded patterns: {sorted(excluded_patterns)}")
    print("-" * 40)
    files = collect_files(root, excluded_dirs, excluded_patterns)
    print(f"Files queued: {len(files)}")
    total = 0
    pool = Pool(processes=WORKER_COUNT)
    try:
        async_results = [pool.apply_async(process_file, (p, args.search_string, args.content)) for p in files]
        pool.close()
        for ar in async_results:
            try:
                results = ar.get()
            except Exception as exc:
                logger.error(f"Worker failed: {exc}")
                continue
            total += _report(results)
    finally:
        pool.join()
    print(f"Total results: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
