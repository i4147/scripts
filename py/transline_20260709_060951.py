
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
import re
from datetime import datetime
from dh import mpf_async, get_nobinary


DELAY_BETWEEN_SEGMENTS = 0.01  
DELAY_BETWEEN_FILES = 1.0  
MAX_RETRIES = 5  
PROGRESS_SAVE_EVERY = 10



logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)



_interrupted = False


def _sigint_handler(sig, frame):
    global _interrupted
    print("\n⚠️  Ctrl+C caught — will stop after current segment.")
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

_CHINESE_PUNCTUATION = set('，。！？；：、""（）【】《》…—～·　　')


def is_chinese_char(ch: str) -> bool:
    if ch in _CHINESE_PUNCTUATION:
        return True
    return any(lo <= ord(ch) <= hi for lo, hi in _CHINESE_RANGES)


def has_chinese(text: str) -> bool:
    return any(is_chinese_char(ch) for ch in text)


def find_chinese_segments(text: str) -> list[tuple[int, int, str]]:
    segments = []
    i = 0
    while i < len(text):
        if is_chinese_char(text[i]):
            start = i
            while i < len(text) and is_chinese_char(text[i]):
                i += 1
            segments.append((start, i, text[start:i]))
        else:
            i += 1
    return segments


def reassemble_line(original: str, translations: dict[tuple[int, int], str]) -> str:
    result = []
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


def save_progress(file_path: Path, done: dict, total: int) -> None:
    try:
        
        serializable_done = {}
        for line_num, segments in done.items():
            if isinstance(segments, dict):
                serializable_segments = {}
                for (start, end), trans in segments.items():
                    key = f"{start},{end}"
                    serializable_segments[key] = trans
                serializable_done[str(line_num)] = serializable_segments
            else:
                serializable_done[str(line_num)] = segments

        state = {
            "file": str(file_path),
            "saved_at": datetime.now().isoformat(),
            "total_lines": total,
            "translations": serializable_done,
        }
        _progress_path(file_path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"   ⚠️  Could not save progress: {e}")


def load_progress(file_path: Path) -> dict:
    p = _progress_path(file_path)
    if not p.exists():
        return {}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
        if Path(state.get("file", "")) != file_path:
            return {}

        restored = {}
        for line_num_str, segments in state["translations"].items():
            line_num = int(line_num_str)
            if isinstance(segments, dict):
                restored_segments = {}
                for key, trans in segments.items():
                    start, end = map(int, key.split(","))
                    restored_segments[(start, end)] = trans
                restored[line_num] = restored_segments
            else:
                restored[line_num] = segments

        total_segments = sum(len(v) if isinstance(v, dict) else 1 for v in restored.values())
        print(f"   🔄 Resuming: {len(restored)} lines with {total_segments} segments already done")
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

    
    line_segments = {}
    for i, ln in enumerate(lines):
        stripped = ln.rstrip("\r\n")
        segments = find_chinese_segments(stripped)
        if segments:
            line_segments[i] = segments

    if not line_segments:
        print(f"   ✅ No Chinese found — skipping")
        drop_progress(path)
        return True

    total_segments = sum(len(segs) for segs in line_segments.values())
    print(f"   🔍 {len(line_segments)} line(s) with {total_segments} Chinese segment(s) to translate")

    
    done: dict = load_progress(path)

    
    for line_idx in line_segments:
        if line_idx not in done:
            done[line_idx] = {}

    
    completed_segments = sum(len(v) if isinstance(v, dict) else 1 for v in done.values())
    segment_count = completed_segments

    for line_idx, segments in line_segments.items():
        if _interrupted:
            save_progress(path, done, len(lines))
            print("   💾 Progress saved. Stopping.")
            return False

        stripped = lines[line_idx].rstrip("\r\n")

        for start, end, chinese_text in segments:
            if _interrupted:
                save_progress(path, done, len(lines))
                print("   💾 Progress saved. Stopping.")
                return False

            
            if (start, end) in done[line_idx]:
                continue

            
            translated, ok = translate_safe(chinese_text)

            if ok:
                done[line_idx][(start, end)] = translated
                status = "✓"
            else:
                done[line_idx][(start, end)] = chinese_text  
                status = "✗"

            segment_count += 1

            
            print(
                f"   [{segment_count:>4}/{total_segments}] {status} line {line_idx + 1}: "
                f"{chinese_text[:20].strip()!r} → {translated[:20].strip()!r}"
            )

            
            if segment_count % PROGRESS_SAVE_EVERY == 0:
                save_progress(path, done, len(lines))

            
            time.sleep(DELAY_BETWEEN_SEGMENTS)

    
    out_lines = []
    for i, line in enumerate(lines):
        if i in done and done[i]:
            eol = line[len(line.rstrip("\r\n")) :]  
            stripped = line.rstrip("\r\n")
            reassembled = reassemble_line(stripped, done[i])
            out_lines.append(reassembled + eol)
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

    
    failed_segments = 0
    for line_idx, segments in line_segments.items():
        if line_idx in done:
            for (start, end), trans in done[line_idx].items():
                if has_chinese(trans):
                    failed_segments += 1

    success_segments = total_segments - failed_segments
    print(f"   ✅ Done — {success_segments}/{total_segments} segments translated successfully")
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
