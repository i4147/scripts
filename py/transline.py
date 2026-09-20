from __future__ import annotations

import json
import logging
import re
import signal
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from deep_translator import GoogleTranslator
from dh import get_nobinary
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

CHUNK_SIZE = 1024 * 1024
CHUNK_SIZE: Final[int] = 32768
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
CHINESE_PATTERN: Final[re.Pattern] = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+")
MAX_WORKERS: Final[int] = 10
MAX_RETRIES: Final[int] = 1
PROGRESS_SAVE_EVERY: Final[int] = 20
logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)
_interrupted = False


def _sigint_handler(sig: Any, frame: Any) -> None:
    global _interrupted
    print("\n⚠️  Ctrl+C caught — completing current active requests and saving progress...")
    _interrupted = True


signal.signal(signal.SIGINT, _sigint_handler)


def find_chinese_segments(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group()) for m in CHINESE_PATTERN.finditer(text)]


def reassemble_line(original: str, translations: dict[tuple[int, int], str]) -> str:
    result: list[str] = []
    last_end = 0
    for (start, end), translated in sorted(translations.items()):
        result.append(original[last_end:start])
        result.append(translated)
        last_end = end
    result.append(original[last_end:])
    return "".join(result)


def read_text(path: Path) -> tuple[str, str]:
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk", "cp1252"):
        try:
            return (path.read_text(encoding=enc, errors="strict"), enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return (path.read_bytes().decode("utf-8", errors="replace"), "utf-8")


class RateLimitError(Exception):
    pass


class TranslationError(Exception):
    pass


@retry(
    reraise=True,
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=10, jitter=2),
    retry=retry_if_exception_type((RateLimitError, TranslationError)),
    before_sleep=before_sleep_log(log, logging.DEBUG),
)
def _translate(text: str) -> str:
    try:
        result = GoogleTranslator(source="auto", target="en").translate(text)
        if result is None:
            raise TranslationError("Translator returned None")
        if CHINESE_PATTERN.search(result):
            raise TranslationError("Result still contains Chinese")
        return result
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("429", "rate limit", "too many", "quota")):
            raise RateLimitError(str(e))
        raise TranslationError(str(e))


def translate_worker(line_idx: int, start: int, end: int, text: str) -> tuple[int, int, int, str, bool]:
    if _interrupted:
        return (line_idx, start, end, text, False)
    try:
        return (line_idx, start, end, _translate(text), True)
    except Exception:
        return (line_idx, start, end, text, False)


def _progress_path(file_path: Path) -> Path:
    return file_path.with_suffix(file_path.suffix + ".xlprogress")


def save_progress(file_path: Path, done: dict[int, dict[tuple[int, int], str]], total: int) -> None:
    try:
        serializable_done = {str(k): {f"{pos[0]},{pos[1]}": v for pos, v in v.items()} for k, v in done.items() if v}
        state = {
            "file": str(file_path),
            "saved_at": datetime.now().isoformat(),
            "total_lines": total,
            "translations": serializable_done,
        }
        _progress_path(file_path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("Could not save progress for %s: %s", file_path, e)


def load_progress(file_path: Path) -> dict[int, dict[tuple[int, int], str]]:
    p = _progress_path(file_path)
    if not p.exists():
        return {}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
        restored: dict[int, dict[tuple[int, int], str]] = {}
        for line_num_str, segments in state.get("translations", {}).items():
            line_idx = int(line_num_str)
            restored[line_idx] = {tuple(map(int, k.split(","))): v for k, v in segments.items()}
        return restored
    except Exception:
        return {}


def drop_progress(file_path: Path) -> None:
    _progress_path(file_path).unlink(missing_ok=True)


def process_file(path: Path) -> bool:
    global _interrupted
    print(f"\n📄 Processing: {path}")
    try:
        text, enc = read_text(path)
    except Exception as e:
        print(f"   ❌ Cannot read file: {e}")
        return False
    lines = text.splitlines(keepends=True)
    line_segments: dict[int, list[tuple[int, int, str]]] = {}
    for i, ln in enumerate(lines):
        if segments := find_chinese_segments(ln.rstrip("\r\n")):
            line_segments[i] = segments
    if not line_segments:
        print("   ✅ No Chinese characters found — skipping")
        drop_progress(path)
        return True
    total_segments = sum(len(segs) for segs in line_segments.values())
    done = load_progress(path)
    tasks: list[tuple[int, int, int, str]] = []
    for line_idx, segments in line_segments.items():
        if line_idx not in done:
            done[line_idx] = {}
        for start, end, chinese_text in segments:
            if (start, end) not in done[line_idx]:
                tasks.append((line_idx, start, end, chinese_text))
    completed_segments = total_segments - len(tasks)
    if completed_segments > 0:
        print(f"   🔄 Resuming: {completed_segments}/{total_segments} segments already cached")
    if tasks:
        print(f"   ⚡ Launching {MAX_WORKERS} threads for {len(tasks)} segments...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_seg = {executor.submit(translate_worker, *task): task for task in tasks}
            for future in as_completed(future_to_seg):
                l_idx, s, e, result_text, success = future.result()
                done[l_idx][s, e] = result_text
                completed_segments += 1
                status = "✓" if success else "❌ Failed"
                print(f"   [{completed_segments:>4}/{total_segments}] {status} line {l_idx + 1}")
                if completed_segments % PROGRESS_SAVE_EVERY == 0 or _interrupted:
                    save_progress(path, done, len(lines))
                    if _interrupted:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
    if _interrupted:
        return False
    out_content = []
    for i, line in enumerate(lines):
        if done.get(i):
            stripped = line.rstrip("\r\n")
            eol = line[len(stripped) :]
            out_content.append(reassemble_line(stripped, done[i]) + eol)
        else:
            out_content.append(line)
    try:
        path.write_text("".join(out_content), encoding=enc, errors="replace")
        drop_progress(path)
        print("   ✅ Done.")
        return True
    except Exception as e:
        print(f"   ❌ Failed to write output: {e}")
        return False


def main() -> None:
    args = sys.argv[1:]
    files = [Path(p) for p in args if Path(p).is_file()] if args else get_nobinary(Path.cwd())
    for f in files:
        if _interrupted:
            break
        process_file(f)
    if _interrupted:
        print("\n⚠️  Stopped early. Run again to resume.")
    else:
        print("\n✅ All files processed successfully.")


if __name__ == "__main__":
    raise SystemExit(main())
