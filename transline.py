import json
import re
import signal
import sys
from collections.abc import Iterable
from datetime import datetime
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Any, Final
from deep_translator import GoogleTranslator
from dh import get_nobinary
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
CHUNK_SIZE = 32768
SKIP_DIRS = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+")
POOL_SIZE = 8
MAX_RETRIES = 1
PROGRESS_SAVE_EVERY = 20
_interrupted = False
Segment = tuple[int, int, str]
SegmentKey = tuple[int, int]
LineTranslations = dict[SegmentKey, str]
ProgressMap = dict[int, LineTranslations]
def _sigint_handler(sig, frame):
    global _interrupted
    logger.warning(
        "Ctrl+C caught — completing current active requests and saving progress..."
    )
    _interrupted = True
signal.signal(signal.SIGINT, _sigint_handler)
def find_chinese_segments(text):
    return [(m.start(), m.end(), m.group()) for m in CHINESE_PATTERN.finditer(text)]
def reassemble_line(original, translations):
    result = []
    last_end = 0
    for (start, end), translated in sorted(translations.items()):
        result.append(original[last_end:start])
        result.append(translated)
        last_end = end
    result.append(original[last_end:])
    return "".join(result)
def read_text(path):
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk", "cp1252"):
        try:
            return path.read_text(encoding=enc, errors="strict"), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_bytes().decode("utf-8", errors="replace"), "utf-8"
class RateLimitError(Exception):
    pass
class TranslationError(Exception):
    pass
@retry(
    reraise=True,
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=10, jitter=2),
    retry=retry_if_exception_type((RateLimitError, TranslationError)),
)
def _translate(text):
    try:
        result = GoogleTranslator(source="auto", target="en").translate(text)
        if result is None:
            raise TranslationError("Translator returned None")
        if CHINESE_PATTERN.search(result):
            raise TranslationError("Result still contains Chinese")
        return result
    except (RateLimitError, TranslationError):
        raise
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("429", "rate limit", "too many", "quota")):
            raise RateLimitError(str(e)) from e
        raise TranslationError(str(e)) from e
def translate_worker(line_idx, start, end, text):
    if _interrupted:
        return line_idx, start, end, text, False
    try:
        return line_idx, start, end, _translate(text), True
    except Exception as e:
        logger.debug("Translation failed for segment at line {}: {}", line_idx + 1, e)
        return line_idx, start, end, text, False
def _progress_path(path):
    return path.with_suffix(path.suffix + ".xlprogress")
def save_progress(path, done, total):
    try:
        serializable_done = {
            str(k): {f"{pos[0]},{pos[1]}": v for pos, v in v.items()}
            for k, v in done.items()
            if v
        }
        state = {
            "file": str(path),
            "saved_at": datetime.now().isoformat(),
            "total_lines": total,
            "translations": serializable_done,
        }
        _progress_path(path).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.error("Could not save progress for {}: {}", path, e)
def load_progress(path):
    p = _progress_path(path)
    if not p.exists():
        return {}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
        restored = {}
        for line_num_str, segments in state.get("translations", {}).items():
            line_idx = int(line_num_str)
            restored[line_idx] = {
                tuple(map(int, k.split(","))): v for k, v in segments.items()
            }  
        return restored
    except Exception:
        return {}
def drop_progress(path):
    _progress_path(path).unlink(missing_ok=True)
def process_file(path):
    global _interrupted
    print("📄 Processing: {}", path)
    try:
        text, enc = read_text(path)
    except Exception as e:
        logger.error("Cannot read file: {}", e)
        return False
    lines = text.splitlines(keepends=True)
    line_segments = {}
    for i, ln in enumerate(lines):
        stripped = ln.rstrip("\r\n")
        if segments := find_chinese_segments(stripped):
            line_segments[i] = segments
    if not line_segments:
        print("✅ No Chinese characters found — skipping")
        drop_progress(path)
        return True
    total_segments = sum(len(segs) for segs in line_segments.values())
    done = load_progress(path)
    tasks = []
    for line_idx, segments in line_segments.items():
        done.setdefault(line_idx, {})
        for start, end, chinese_text in segments:
            if (start, end) not in done[line_idx]:
                tasks.append((line_idx, start, end, chinese_text))
    completed_segments = total_segments - len(tasks)
    if completed_segments > 0:
        print(
            "🔄 Resuming: {}/{} segments already cached",
            completed_segments,
            total_segments,
        )
    if tasks and not _interrupted:
        print("⚡ Launching {} processes for {} segments...", POOL_SIZE, len(tasks))
        pool = Pool(processes=POOL_SIZE)
        try:
            async_results = [
                (task, pool.apply_async(translate_worker, task)) for task in tasks
            ]
            for task, ar in async_results:
                if _interrupted:
                    break
                l_idx, s, e, result_text, success = ar.get()
                done[l_idx][s, e] = result_text
                completed_segments += 1
                status = "✓" if success else "❌ Failed"
                print(
                    "[{:>4}/{}] {} line {}",
                    completed_segments,
                    total_segments,
                    status,
                    l_idx + 1,
                )
                if completed_segments % PROGRESS_SAVE_EVERY == 0:
                    save_progress(path, done, len(lines))
        finally:
            if _interrupted:
                pool.terminate()
            else:
                pool.close()
            pool.join()
        if _interrupted:
            save_progress(path, done, len(lines))
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
        print("✅ Done.")
        return True
    except Exception as e:
        logger.error("Failed to write output: {}", e)
        return False
def main():
    args = sys.argv[1:]
    files = (
        [Path(p) for p in args if Path(p).is_file()]
        if args
        else get_nobinary(Path.cwd())
    )
    for f in files:
        if _interrupted:
            break
        process_file(f)
    if _interrupted:
        logger.warning("⚠️  Stopped early. Run again to resume.")
        return 130
    print("✅ All files processed successfully.")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
