from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from deep_translator import GoogleTranslator
from dh import get_files
import sys
import time
import random
import signal
import json
from datetime import datetime

MAX_WORKERS = 6
DELAY_BETWEEN_REQUESTS = 0.5
DELAY_BETWEEN_FILES = 2.0
RATE_LIMIT_BACKOFF = 5
MAX_TRANSLATION_RETRIES = 3
interrupt_occurred = False
temp_state_file = None
current_file_path = None
current_translations = {}
current_file_lines = []


def signal_handler(sig, frame):
    global interrupt_occurred
    print("\n\n⚠️  Interrupt received! Saving progress...")
    interrupt_occurred = True
    save_temp_state()
    print("✅ Progress saved. Exiting...")
    sys.exit(0)


def save_temp_state():
    global temp_state_file, current_file_path, current_translations, current_file_lines
    if not current_file_path or not current_translations:
        return
    try:
        temp_file = current_file_path.with_suffix(current_file_path.suffix + ".translation_progress")
        state = {
            "file_path": str(current_file_path),
            "timestamp": datetime.now().isoformat(),
            "translations": current_translations,
            "total_lines": len(current_file_lines),
            "translated_count": len(current_translations),
        }
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"💾 Progress saved to: {temp_file}")
        temp_state_file = temp_file
    except Exception as e:
        print(f"⚠️  Error saving temp state: {e}")


def load_temp_state(file_path: Path) -> dict | None:
    temp_file = file_path.with_suffix(file_path.suffix + ".translation_progress")
    if not temp_file.exists():
        return None
    try:
        with open(temp_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        if Path(state["file_path"]) != file_path:
            return None
        print(f"🔄 Found saved progress: {state['translated_count']} lines already translated")
        return state["translations"]
    except Exception as e:
        print(f"⚠️  Error loading temp state: {e}")
        return None


def cleanup_temp_state(file_path: Path):
    temp_file = file_path.with_suffix(file_path.suffix + ".translation_progress")
    if temp_file.exists():
        try:
            temp_file.unlink()
            print(f"🧹 Cleaned up temp file: {temp_file}")
        except Exception as e:
            print(f"⚠️  Error cleaning up temp file: {e}")


def translate_line(line: str, retry_count: int = 0) -> tuple[str, bool]:
    try:
        result = GoogleTranslator(source="auto", target="en").translate(line)
        if has_chinese_chars(result):
            if retry_count < MAX_TRANSLATION_RETRIES:
                wait_time = RATE_LIMIT_BACKOFF * (retry_count + 1) + random.uniform(0, 2)
                print(
                    f"🔄 Translation still has Chinese chars, retry {retry_count + 1}/{MAX_TRANSLATION_RETRIES} in {wait_time:.1f}s"
                )
                time.sleep(wait_time)
                return translate_line(line, retry_count + 1)
            else:
                print(f"❌ Failed to translate after {MAX_TRANSLATION_RETRIES} retries: {line[:50]}...")
                return (line, False)
        return (result, True)
    except Exception as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg or "too many" in error_msg or "429" in error_msg:
            if retry_count < MAX_TRANSLATION_RETRIES:
                wait_time = RATE_LIMIT_BACKOFF * (retry_count + 1) + random.uniform(0, 2)
                print(f"⏳ Rate limit hit! Retry {retry_count + 1}/{MAX_TRANSLATION_RETRIES} in {wait_time:.1f}s...")
                time.sleep(wait_time)
                return translate_line(line, retry_count + 1)
            else:
                print(f"❌ Rate limit persists after {MAX_TRANSLATION_RETRIES} retries")
                return (line, False)
        elif "timeout" in error_msg or "timed out" in error_msg:
            if retry_count < MAX_TRANSLATION_RETRIES:
                wait_time = 2 * (retry_count + 1) + random.uniform(0, 1)
                print(f"⏱️ Timeout! Retry {retry_count + 1}/{MAX_TRANSLATION_RETRIES} in {wait_time:.1f}s...")
                time.sleep(wait_time)
                return translate_line(line, retry_count + 1)
            else:
                print(f"❌ Timeout persists after {MAX_TRANSLATION_RETRIES} retries")
                return (line, False)
        else:
            print(f"❌ Translation error: {e}")
            return (line, False)


def has_chinese_chars(s: str) -> bool:
    for ch in s:
        code = ord(ch)
        if (
            13312 <= code <= 19903
            or 19968 <= code <= 40959
            or 63744 <= code <= 64255
            or (131072 <= code <= 173791)
            or (173824 <= code <= 177983)
            or (177984 <= code <= 178207)
            or (178208 <= code <= 183983)
            or (183984 <= code <= 191471)
        ):
            return True
    return False


def read_text_maybe(path: Path) -> tuple[str, str]:
    encodings = ("utf-8", "utf-8-sig", "gb18030", "gbk", "cp1252")
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return (f.read(), enc)
        except UnicodeDecodeError:
            continue
    with open(path, "rb") as f:
        return (f.read().decode("utf-8", errors="replace"), "utf-8")


def translate_chinese_lines(lines: list[str], line_indices: list[int]) -> dict[int, str]:
    global current_translations, current_file_lines
    translations = {}
    failed_indices = set(line_indices)
    saved_translations = load_temp_state(current_file_path)
    if saved_translations:
        translations.update(saved_translations)
        for idx in saved_translations:
            if idx in failed_indices:
                failed_indices.remove(idx)
        print(f"📂 Loaded {len(saved_translations)} previously translated lines")
    if not failed_indices:
        print("✅ All lines already translated!")
        return translations

    def translate_single(idx_line):
        idx, line = idx_line
        time.sleep(random.uniform(0.1, 0.3))
        translated, success = translate_line(line)
        return (idx, translated, success)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(translate_single, (idx, lines[idx])): idx for idx in failed_indices}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                idx, translated, success = future.result()
                if success:
                    translations[idx] = translated
                    current_translations = translations
                    if len(translations) % 5 == 0:
                        save_temp_state()
                else:
                    translations[idx] = lines[idx].rstrip("\r\n")
                    print(f"⚠️  Keeping original for line {idx + 1} (translation failed)")
                time.sleep(DELAY_BETWEEN_REQUESTS)
            except Exception as e:
                print(f"❌ Error processing translation: {e}")
                translations[idx] = lines[idx].rstrip("\r\n")
    return translations


def process_file_inplace(path: Path) -> None:
    global current_file_path, current_translations, current_file_lines, interrupt_occurred
    current_file_path = path
    current_translations = {}
    current_file_lines = []
    interrupt_occurred = False
    try:
        print(f"\n📁 Processing: {path}")
        text, enc = read_text_maybe(path)
        lines = text.splitlines(keepends=True)
        current_file_lines = lines
        chinese_lines = []
        for i, line in enumerate(lines):
            content = line.rstrip("\r\n")
            if has_chinese_chars(content):
                chinese_lines.append(i)
        if not chinese_lines:
            print(f"✅ No Chinese chars found: {path}")
            cleanup_temp_state(path)
            return
        print(f"🔍 Found {len(chinese_lines)} Chinese lines to translate")
        print(f"⚙️  Using {MAX_WORKERS} parallel workers with {DELAY_BETWEEN_REQUESTS}s delay")
        translations = translate_chinese_lines(lines, chinese_lines)
        still_chinese = []
        for idx, translated in translations.items():
            if has_chinese_chars(translated):
                still_chinese.append(idx)
        if still_chinese:
            print(f"⚠️  {len(still_chinese)} lines still contain Chinese after all retries")
        out_lines = []
        for i, line in enumerate(lines):
            if i in translations:
                content = line.rstrip("\r\n")
                out_lines.append(translations[i] + line[len(content) :])
            else:
                out_lines.append(line)
        tmp_path = path.with_suffix(path.suffix + ".tmp_translate")
        with open(tmp_path, "w", encoding=enc, errors="replace", newline="") as f:
            f.writelines(out_lines)
        Path(tmp_path).rename(path)
        print(f"✅ Updated: {path}")
        cleanup_temp_state(path)
    except Exception as e:
        print(f"❌ Error processing {path}: {e}")
        save_temp_state()


def process_files_sequentially(files: list[Path]) -> None:
    for idx, file in enumerate(files):
        if interrupt_occurred:
            break
        print(f"\n{'=' * 50}")
        print(f"📄 File {idx + 1}/{len(files)}: {file.name}")
        print(f"{'=' * 50}")
        process_file_inplace(file)
        if idx < len(files) - 1 and (not interrupt_occurred):
            print(f"\n⏳ Waiting {DELAY_BETWEEN_FILES}s before next file...")
            time.sleep(DELAY_BETWEEN_FILES)


def main():
    signal.signal(signal.SIGINT, signal_handler)
    root = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(root)
    print(f"\n🚀 Starting translation process")
    print(f"📁 Found {len(files)} files to process")
    print(f"⚙️  Settings: {MAX_WORKERS} workers, {DELAY_BETWEEN_REQUESTS}s between requests")
    print(f"🔄 Max retries: {MAX_TRANSLATION_RETRIES}")
    print(f"💾 Temp files will be saved automatically")
    print(f"⚠️  Press Ctrl+C to save progress and exit\n")
    if len(files) == 1:
        process_file_inplace(files[0])
    else:
        process_files_sequentially(files)
    print(f"\n✅ All processing complete!")


if __name__ == "__main__":
    main()
