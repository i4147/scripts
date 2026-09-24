from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, ProcessPoolExecutor
from deep_translator import GoogleTranslator
from dh import get_files
import sys
import multiprocessing as mp


def translate_line(line: str) -> str:
    try:
        result = GoogleTranslator(source="auto", target="en").translate(line)
        print(result)
        print("*" * 33)
        print()
        return result
    except Exception as e:
        print(f"line translation error: {e}")
        return line


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
    translations = {}

    def translate_single(idx_line):
        idx, line = idx_line
        return idx, translate_line(line)

    with ThreadPoolExecutor(max_workers=min(len(line_indices), 12)) as executor:
        futures = {executor.submit(translate_single, (idx, lines[idx])): idx for idx in line_indices}
        for future in as_completed(futures):
            time.sleep(0.5)
            idx, translated = future.result()
            translations[idx] = translated

    return translations


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
    for file in files:
        print(f"\n{'=' * 50}")
        print(f"Processing file: {file}")
        print(f"{'=' * 50}")
        process_file_inplace(file)


def main():
    root = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(root)

    if len(files) == 1:
        process_file_inplace(files[0])
        sys.exit(0)

    process_files_sequentially(files)


if __name__ == "__main__":
    main()
