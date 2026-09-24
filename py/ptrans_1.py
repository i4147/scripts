import argparse
import ast
import os
import time
from multiprocessing import Pool
from pathlib import Path
from deep_translator import GoogleTranslator

DEFAULT_TEXT_EXTENSIONS = {
    ".txt",
    ".py",
    ".md",
    ".html",
    ".css",
    ".js",
    ".json",
    ".dic",
    ".csv",
    ".yaml",
    ".yml",
    ".cfg",
    ".ini",
    ".sh",
    ".bat",
    ".tex",
    ".rst",
    ".log",
    ".conf",
}


def chunk_lines(lines, max_len=5000):
    current_chunk = []
    current_len = 0
    for line in lines:
        line_len = len(line)
        if current_len + line_len > max_len and current_chunk:
            yield "".join(current_chunk)
            current_chunk = [line]
            current_len = line_len
        else:
            current_chunk.append(line)
            current_len += line_len
    if current_chunk:
        yield "".join(current_chunk)


def translate_file(file_path: Path, target_lang: str, delay: float, output_dir: Path = None) -> None:
    print(f"[{os.getpid()}] Processing: {file_path}")
    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        print(f"  Skipping (cannot read): {file_path}  ({e})")
        return
    lines = content.splitlines(keepends=True)
    chunks = list(chunk_lines(lines, max_len=5000))
    if not chunks:
        print(f"  Empty file, skipping: {file_path}")
        return
    translator = GoogleTranslator(source="auto", target=target_lang)
    translated_chunks = []
    for i, chunk in enumerate(chunks, 1):
        try:
            translated = translator.translate(chunk)
        except Exception as e:
            print(f"  Translation error in chunk {i}/{len(chunks)} of {file_path.name}: {e}")
            return
        preview = translated[:120] + ("..." if len(translated) > 120 else "")
        print(f"    Chunk {i}/{len(chunks)}: {preview}")
        translated_chunks.append(translated)
        time.sleep(delay)
    translated_text = "".join(translated_chunks)
    if file_path.suffix.lower() == ".py":
        try:
            ast.parse(translated_text)
        except SyntaxError as e:
            print(f"  ✗ Syntax error in translated Python file, NOT writing: {file_path}")
            print(f"    {e}")
            return
        else:
            print(f"  ✓ Python syntax valid")
    if output_dir:
        try:
            rel_path = file_path.relative_to(Path.cwd())
        except ValueError:
            rel_path = file_path
        out_path = output_dir / rel_path.with_suffix(file_path.suffix + f".{target_lang}")
    else:
        out_path = file_path.with_suffix(file_path.suffix + f".{target_lang}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_path.write_text(translated_text, encoding="utf-8")
        print(f"  → Written: {out_path}")
    except OSError as e:
        print(f"  ✗ Could not write output: {out_path}  ({e})")


def is_text_file(path: Path, extensions: set) -> bool:
    return path.suffix.lower() in extensions


def main():
    parser = argparse.ArgumentParser(description="Translate non‑English text files recursively using Google Translate.")
    parser.add_argument("directory", type=Path, help="Root directory to scan recursively")
    parser.add_argument("--target-lang", default="en", help="Target language code (default: en)")
    parser.add_argument(
        "--delay", type=float, default=1.0, help="Delay in seconds between chunk translations (default: 1.0)"
    )
    parser.add_argument(
        "--workers", type=int, default=os.cpu_count(), help="Number of parallel worker processes (default: CPU count)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to store translated files (default: same folder with '.en' suffix)",
    )
    parser.add_argument(
        "--extensions",
        nargs="*",
        default=None,
        help="File extensions to process (e.g. .py .txt .md). If omitted, a built‑in list is used.",
    )
    args = parser.parse_args()
    if args.extensions:
        extensions = {(ext.lower() if ext.startswith(".") else f".{ext.lower()}") for ext in args.extensions}
    else:
        extensions = DEFAULT_TEXT_EXTENSIONS
    root = args.directory.resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory.")
        return
    files = [f for f in root.rglob("*") if f.is_file() and is_text_file(f, extensions)]
    print(f"Found {len(files)} text files to process.\n")
    with Pool(processes=args.workers) as pool:
        pool.starmap(translate_file, [(f, args.target_lang, args.delay, args.output_dir) for f in files])
    print("\nAll files processed.")


if __name__ == "__main__":
    main()
