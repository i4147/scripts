from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from deep_translator import GoogleTranslator
from dh import get_files
import sys
import time
import random


MAX_WORKERS = 6  
DELAY_BETWEEN_REQUESTS = 0.5  
DELAY_BETWEEN_FILES = 2.0  
RATE_LIMIT_BACKOFF = 5  


def translate_line(line: str, retry_count: int = 0) -> str:
    try:
        result = GoogleTranslator(source="auto", target="en").translate(line)
        print(result)
        print("*" * 33)
        print()
        return result
    except Exception as e:
        error_msg = str(e).lower()

        
        if "rate limit" in error_msg or "too many" in error_msg or "429" in error_msg:
            if retry_count < 3:
                wait_time = RATE_LIMIT_BACKOFF * (retry_count + 1) + random.uniform(0, 1)
                print(f"Rate limit hit! Waiting {wait_time:.1f}s before retry...")
                time.sleep(wait_time)
                return translate_line(line, retry_count + 1)
            else:
                print(f"Rate limit persists after {retry_count} retries: {e}")
                return line
        else:
            print(f"line translation error: {e}")
            return line


def translate_chinese_lines(lines: list[str], line_indices: list[int]) -> dict[int, str]:
    translations = {}

    def translate_single(idx_line):
        idx, line = idx_line

        
        
        time.sleep(random.uniform(0.1, 0.3))

        return idx, translate_line(line)

    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(translate_single, (idx, lines[idx])): idx for idx in line_indices}
        for future in as_completed(futures):
            idx, translated = future.result()
            translations[idx] = translated

            
            time.sleep(DELAY_BETWEEN_REQUESTS)

    return translations


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


def process_file_inplace(path: Path) -> None:
    try:
        text, enc = read_text_maybe(path)
        lines = text.splitlines(keepends=True)

        
        chinese_lines = []
        for i, line in enumerate(lines):
            content = line.rstrip("\r\n")
            if has_chinese_chars(content):
                chinese_lines.append(i)

        if not chinese_lines:
            print(f"No Chinese chars: {path}")
            return

        print(f"Processing {len(chinese_lines)} Chinese lines in {path}")
        print(f"Using {MAX_WORKERS} parallel workers with {DELAY_BETWEEN_REQUESTS}s delay between requests")

        
        translations = translate_chinese_lines(lines, chinese_lines)

        
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
        print(f"Updated: {path}")

    except Exception as e:
        print(f"Error processing {path}: {e}")


def process_files_sequentially(files: list[Path]) -> None:
    for idx, file in enumerate(files):
        print(f"\n{'=' * 50}")
        print(f"Processing file {idx + 1}/{len(files)}: {file}")
        print(f"{'=' * 50}")
        process_file_inplace(file)

        
        if idx < len(files) - 1:  
            print(f"\nWaiting {DELAY_BETWEEN_FILES}s before next file...")
            time.sleep(DELAY_BETWEEN_FILES)


def main():
    root = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(root)

    print(f"Found {len(files)} files to process")
    print(f"Rate limit settings: {MAX_WORKERS} workers, {DELAY_BETWEEN_REQUESTS}s between requests")
    print(f"Backoff delay on rate limit: {RATE_LIMIT_BACKOFF}s")
    print()

    if len(files) == 1:
        process_file_inplace(files[0])
        sys.exit(0)

    
    process_files_sequentially(files)


if __name__ == "__main__":
    main()
