from pathlib import Path
from deep_translator import GoogleTranslator
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
    before_sleep_log,
)
import sys
import time
import json
import signal
import logging
from datetime import datetime
from dh import mpf_async, get_nobinary


DELAY_BETWEEN_LINES = 0.01
DELAY_BETWEEN_FILES = 1.0
MAX_RETRIES = 5
PROGRESS_SAVE_EVERY = 10


logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)


_interrupted = False


def _sigint_handler(sig, frame):
    global _interrupted
    print("\n⚠️  Ctrl+C caught — will stop after current line.")
    _interrupted = True


signal.signal(signal.SIGINT, _sigint_handler)


_CHINESE_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
    (0x2CEB0, 0x2EBEF),
)


def has_chinese(text: str) -> bool:
    return any(lo <= ord(ch) <= hi for ch in text for lo, hi in _CHINESE_RANGES)


def read_text(path: Path) -> tuple[str, str]:
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
    wait=wait_exponential_jitter(initial=2, max=60, jitter=3),
    retry=retry_if_exception_type((RateLimitError, TranslationError)),
    before_sleep=before_sleep_log(log, logging.DEBUG),
)
def _translate(text: str) -> str:
    try:
        result = GoogleTranslator(source="auto", target="en").translate(text)
        if result is None:
            raise TranslationError("Translator returned None")
        if has_chinese(result):
            raise TranslationError(f"Result still contains Chinese: {result[:40]}")
        return result
    except (RateLimitError, TranslationError):
        raise
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("429", "rate limit", "too many", "quota")):
            print(f"   ⏳ Rate limited — backing off…")
            raise RateLimitError(str(e))
        if any(k in msg for k in ("timeout", "timed out", "connection")):
            raise TranslationError(str(e))
        raise TranslationError(str(e))


def translate_safe(text: str) -> tuple[str, bool]:
    try:
        return _translate(text), True
    except Exception as e:
        print(f"   ❌ Gave up translating: {e}")
        return text, False


def _progress_path(file_path: Path) -> Path:
    return file_path.with_suffix(file_path.suffix + ".xlprogress")


def save_progress(file_path: Path, done: dict[int, str], total: int) -> None:
    try:
        state = {
            "file": str(file_path),
            "saved_at": datetime.now().isoformat(),
            "total_lines": total,
            "translations": {str(k): v for k, v in done.items()},
        }
        _progress_path(file_path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"   ⚠️  Could not save progress: {e}")


def load_progress(file_path: Path) -> dict[int, str]:
    p = _progress_path(file_path)
    if not p.exists():
        return {}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
        if Path(state.get("file", "")) != file_path:
            return {}
        restored = {int(k): v for k, v in state["translations"].items()}
        print(f"   🔄 Resuming: {len(restored)} lines already done")
        return restored
    except Exception:
        return {}


def drop_progress(file_path: Path) -> None:
    p = _progress_path(file_path)
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass


def process_file(path: Path) -> bool:
    global _interrupted

    print(f"\n📄 {path}")
    try:
        text, enc = read_text(path)
    except Exception as e:
        print(f"   ❌ Cannot read file: {e}")
        return False

    lines = text.splitlines(keepends=True)
    chinese_indices = [i for i, ln in enumerate(lines) if has_chinese(ln.rstrip("\r\n"))]

    if not chinese_indices:
        print(f"   ✅ No Chinese found — skipping")
        drop_progress(path)
        return True

    print(f"   🔍 {len(chinese_indices)} line(s) to translate")

    done: dict[int, str] = load_progress(path)
    remaining = [i for i in chinese_indices if i not in done]
    total = len(chinese_indices)

    for count, idx in enumerate(remaining, start=1):
        if _interrupted:
            save_progress(path, done, len(lines))
            print("   💾 Progress saved. Stopping.")
            return False

        original = lines[idx].rstrip("\r\n")
        translated, ok = translate_safe(original)

        if ok:
            done[idx] = translated
            status = "✓"
        else:
            done[idx] = original
            status = "✗"

        completed = len(done)
        print(
            f"   [{completed:>4}/{total}] {status} line {idx + 1}: "
            f"{original[:30].strip()!r} → {translated[:30].strip()!r}"
        )

        if completed % PROGRESS_SAVE_EVERY == 0:
            save_progress(path, done, len(lines))

        if count < len(remaining):
            time.sleep(DELAY_BETWEEN_LINES)

    out_lines = []
    for i, line in enumerate(lines):
        if i in done:
            eol = line[len(line.rstrip("\r\n")) :]
            out_lines.append(done[i] + eol)
        else:
            out_lines.append(line)

    tmp = path.with_suffix(path.suffix + ".xltmp")
    try:
        tmp.write_text("".join(out_lines), encoding=enc, errors="replace")
        tmp.rename(path)
    except Exception as e:
        print(f"   ❌ Failed to write output: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False

    drop_progress(path)
    failed = sum(1 for i in chinese_indices if has_chinese(done.get(i, "")))
    print(f"   ✅ Done — {total - failed}/{total} lines translated successfully")
    return True


def main():
    args = sys.argv[1:]

    if args:
        files = [Path(p) for p in args if Path(p).is_file()]
    else:
        files = get_nobinary(Path.cwd())

    for i, f in enumerate(files):
        if _interrupted:
            break
        process_file(f)
        if i < len(files) - 1 and not _interrupted:
            time.sleep(DELAY_BETWEEN_FILES)

    if _interrupted:
        print("\n⚠️  Stopped early. Run again to resume from saved progress.")
    else:
        print("\n✅ All done.")


if __name__ == "__main__":
    main()
