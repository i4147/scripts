import re
import shutil
import sys
import tempfile
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final
from deep_translator import GoogleTranslator
from loguru import logger
NON_ENGLISH_PATTERN = re.compile(r"[^\x00-\x7F]")
MAX_WORKERS = 8
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
    }
)
def is_english(text):
    return not NON_ENGLISH_PATTERN.search(text)
def get_files(path, include_hidden=True, extensions=None):
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")
    files = []
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            for entry in current.iterdir():
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in SKIP_DIRS:
                        stack.append(entry)
                elif entry.is_file():
                    if not include_hidden and entry.name.startswith("."):
                        continue
                    if extensions is None or entry.suffix.lower() in extensions:
                        files.append(entry)
        except PermissionError:
            logger.warning("Permission denied: {}", current)
            continue
    return sorted(files)
def translate_text(text):
    if not text:
        return text
    lines = text.splitlines(keepends=True)
    translated_lines = []
    translator = GoogleTranslator(source="auto", target="en")
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line or is_english(stripped_line):
            translated_lines.append(line)
        else:
            try:
                result = translator.translate(stripped_line)
                ending = "\n" if line.endswith("\n") else ""
                translated_lines.append(f"{result}{ending}" if result else line)
            except Exception as e:
                logger.error("Translation error on line: {}", e)
                translated_lines.append(line)
    return "".join(translated_lines)
def safe_overwrite(path, content):
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=path.parent
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        shutil.move(str(tmp_path), str(path))
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to overwrite {path}: {e}") from e
def process_file(path):
    try:
        original = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"Error reading {path}: {e}"
    if is_english(original.strip()):
        return f"Skipped (English): {path.name}"
    try:
        translated = translate_text(original)
        if translated.strip() != original.strip():
            safe_overwrite(path, translated)
            return f"✓ Updated: {path.name}"
        return f"No changes: {path.name}"
    except Exception as e:
        return f"Failed to process {path}: {e}"
def main():
    args = sys.argv[1:]
    cwd = Path.cwd()
    if args:
        files = [Path(p) for p in args if Path(p).is_file()]
    else:
        files = get_files(cwd, extensions=(".md", ".txt"))
    if not files:
        print("No files found to process.")
        return
    print("Starting processing of {} files...", len(files))
    pool = Pool(processes=MAX_WORKERS)
    try:
        results = [pool.apply_async(process_file, (f,)) for f in files]
        pool.close()
        for result in results:
            try:
                print(result.get())
            except Exception as e:
                logger.error("Worker error: {}", e)
        pool.join()
    finally:
        pool.terminate()
if __name__ == "__main__":
    raise SystemExit(main())
