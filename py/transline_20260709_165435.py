

"""
Translate Chinese characters in text files in-place.
Optimized for speed using parallel processing.
Only translates Chinese characters (not punctuation), preserving everything else.
"""
from pathlib import Path
from deep_translator import GoogleTranslator
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type, before_sleep_log
import sys
import time
import json
import signal
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dh import get_nobinary
MAX_WORKERS = 10
MAX_RETRIES = 3
PROGRESS_SAVE_EVERY = 20
logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)
_interrupted = False

def _sigint_handler(sig, frame):
    global _interrupted
    print('\n⚠️  Ctrl+C caught — completing current active requests and saving progress...')
    _interrupted = True
signal.signal(signal.SIGINT, _sigint_handler)
_CHINESE_RANGES = ((13312, 19903), (19968, 40959), (63744, 64255), (131072, 173791), (173824, 177983), (177984, 178207), (178208, 183983), (183984, 191471))

def is_chinese_ideograph(ch: str) -> bool:
    return any((lo <= ord(ch) <= hi for lo, hi in _CHINESE_RANGES))

def has_chinese(text: str) -> bool:
    return any((is_chinese_ideograph(ch) for ch in text))

def find_chinese_segments(text: str) -> list[tuple[int, int, str]]:
    segments = []
    i = 0
    while i < len(text):
        if is_chinese_ideograph(text[i]):
            start = i
            while i < len(text) and is_chinese_ideograph(text[i]):
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
    return ''.join(result)

def read_text(path: Path) -> tuple[str, str]:
    for enc in ('utf-8', 'utf-8-sig', 'gb18030', 'gbk', 'cp1252'):
        try:
            return (path.read_text(encoding=enc, errors='strict'), enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return (path.read_bytes().decode('utf-8', errors='replace'), 'utf-8')

class RateLimitError(Exception):
    pass

class TranslationError(Exception):
    pass

@retry(reraise=True, stop=stop_after_attempt(MAX_RETRIES), wait=wait_exponential_jitter(initial=1, max=10, jitter=2), retry=retry_if_exception_type((RateLimitError, TranslationError)), before_sleep=before_sleep_log(log, logging.DEBUG))
def _translate(text: str) -> str:
    try:
        result = GoogleTranslator(source='auto', target='en').translate(text)
        if result is None:
            raise TranslationError('Translator returned None')
        if has_chinese(result):
            raise TranslationError(f'Result still contains Chinese')
        return result
    except Exception as e:
        msg = str(e).lower()
        if any((k in msg for k in ('429', 'rate limit', 'too many', 'quota'))):
            raise RateLimitError(str(e))
        raise TranslationError(str(e))

def translate_worker(line_idx: int, start: int, end: int, text: str):
    if _interrupted:
        return (line_idx, start, end, text, False)
    try:
        return (line_idx, start, end, _translate(text), True)
    except Exception:
        return (line_idx, start, end, text, False)

def _progress_path(file_path: Path) -> Path:
    return file_path.with_suffix(file_path.suffix + '.xlprogress')

def save_progress(file_path: Path, done: dict, total: int) -> None:
    try:
        serializable_done = {}
        for line_num, segments in done.items():
            if isinstance(segments, dict):
                serializable_done[str(line_num)] = {f'{k[0]},{k[1]}': v for k, v in segments.items()}
        state = {'file': str(file_path), 'saved_at': datetime.now().isoformat(), 'total_lines': total, 'translations': serializable_done}
        _progress_path(file_path).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        print(f'   ⚠️  Could not save progress: {e}')

def load_progress(file_path: Path) -> dict:
    p = _progress_path(file_path)
    if not p.exists():
        return {}
    try:
        state = json.loads(p.read_text(encoding='utf-8'))
        restored = {}
        for line_num_str, segments in state['translations'].items():
            line_num = int(line_num_str)
            restored_segments = {}
            for key, trans in segments.items():
                start, end = map(int, key.split(','))
                restored_segments[start, end] = trans
            restored[line_num] = restored_segments
        return restored
    except Exception:
        return {}

def drop_progress(file_path: Path) -> None:
    p = _progress_path(file_path)
    if p.exists():
        p.unlink(missing_ok=True)

def process_file(path: Path) -> bool:
    global _interrupted
    print(f'\n📄 {path}')
    try:
        text, enc = read_text(path)
    except Exception as e:
        print(f'   ❌ Cannot read file: {e}')
        return False
    lines = text.splitlines(keepends=True)
    line_segments = {}
    for i, ln in enumerate(lines):
        stripped = ln.rstrip('\r\n')
        segments = find_chinese_segments(stripped)
        if segments:
            line_segments[i] = segments
    if not line_segments:
        print(f'   ✅ No Chinese characters found — skipping')
        drop_progress(path)
        return True
    total_segments = sum((len(segs) for segs in line_segments.values()))
    done = load_progress(path)
    for line_idx in line_segments:
        if line_idx not in done:
            done[line_idx] = {}
    tasks = []
    for line_idx, segments in line_segments.items():
        for start, end, chinese_text in segments:
            if (start, end) not in done[line_idx]:
                tasks.append((line_idx, start, end, chinese_text))
    completed_segments = total_segments - len(tasks)
    if completed_segments > 0:
        print(f'   🔄 Resuming: {completed_segments}/{total_segments} segments already cached')
    if tasks:
        print(f'   ⚡ Launching {MAX_WORKERS} parallel threads for {len(tasks)} segments...')
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(translate_worker, l_idx, s, e, txt): (l_idx, s, e, txt) for l_idx, s, e, txt in tasks}
            for future in as_completed(futures):
                l_idx, s, e, result_text, success = future.result()
                done[l_idx][s, e] = result_text
                completed_segments += 1
                status = '✓' if success else '❌ Failed'
                print(f'   [{completed_segments:>4}/{total_segments}] {status} line {l_idx + 1}')
                if completed_segments % PROGRESS_SAVE_EVERY == 0 or _interrupted:
                    save_progress(path, done, len(lines))
                    if _interrupted:
                        break
    out_lines = []
    for i, line in enumerate(lines):
        if i in done and done[i]:
            eol = line[len(line.rstrip('\r\n')):]
            stripped = line.rstrip('\r\n')
            reassembled = reassemble_line(stripped, done[i])
            out_lines.append(reassembled + eol)
        else:
            out_lines.append(line)
    tmp = path.with_suffix(path.suffix + '.xltmp')
    try:
        tmp.write_text(''.join(out_lines), encoding=enc, errors='replace')
        tmp.rename(path)
    except Exception as e:
        print(f'   ❌ Failed to write output: {e}')
        return False
    finally:
        tmp.unlink(missing_ok=True)
    if not _interrupted:
        drop_progress(path)
        print(f'   ✅ Done.')
        return True
    return False

def main():
    args = sys.argv[1:]
    files = [Path(p) for p in args if Path(p).is_file()] if args else get_nobinary(Path.cwd())
    for f in files:
        if _interrupted:
            break
        process_file(f)
    if _interrupted:
        print('\n⚠️  Stopped early. Run again to resume from saved progress.')
    else:
        print('\n✅ All done processing all files.')
if __name__ == '__main__':
    main()
replace hard coded chinese char detection login with
import re

# This regex pattern explicitly matches ANY Han (Chinese) character, 
# completely ignoring brackets, spaces, or English characters automatically.
CHINESE_PATTERN = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+')

segments = CHINESE_PATTERN.findall(text)