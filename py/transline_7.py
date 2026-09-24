from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from deep_translator import GoogleTranslator
from dh import get_files

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


def process_file_inplace(path: Path) -> None:
    try:
        text, enc = read_text_maybe(path)
        lines = text.splitlines(keepends=True)
        changed = False
        out_lines = []
        for line in lines:
            content = line.rstrip("\r\n")
            if has_chinese_chars(content):
                translated = translate_line(content)
                out_lines.append(translated + line[len(content) :])
                changed = True
            else:
                out_lines.append(line)
        if changed:
            tmp_path = path.with_suffix(path.suffix + ".tmp_translate")
            with open(tmp_path, "w", encoding=enc, errors="replace", newline="") as f:
                f.writelines(out_lines)
            Path(tmp_path).rename(path)
            print(f"Updated: {path}")
        else:
            print(f"No Chinese chars: {path}")
    except Exception as e:
        print(f"Error processing {path}: {e}")


def process_file_batch(files: list[Path], max_workers: int = 12) -> None:
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(process_file_inplace, file): file for file in files}
        for future in as_completed(futures):
            file = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"Failed to process {file}: {e}")


def main():
    root = Path.cwd()
    args=sys.argv[1:]
    files=[Path(p) for in args] if args else get_files(cwd)
    if len(files)==1:
        process_file_inplace(files[0])
        sys.exit(0)
    process_file_batch(files, max_workers=4)


if __name__ == "__main__":
    main()