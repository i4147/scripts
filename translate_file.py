import re
import sys
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
from typing import Final, List, Optional
from deep_translator import GoogleTranslator
from loguru import logger
POOL_SIZE = 8
FILE_PATTERNS = ("*.txt", "*.md", "*.py", "*.json", "*.csv")
SKIP_DIRS = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
LANGUAGE_PATTERN = re.compile(
    r"[\u0600-\u06FF\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF\u0400-\u04FF]"
)
def is_foreign_line(line):
    return bool(LANGUAGE_PATTERN.search(line))
def _should_skip(path):
    for part in path.parts:
        if part.startswith(".") or part in SKIP_DIRS:
            return True
    return False
def process_file(file_path):
    try:
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        translator = GoogleTranslator(source="auto", target="en")
        modified = False
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and is_foreign_line(stripped):
                try:
                    translated_raw = translator.translate(stripped)
                    translated = (
                        translated_raw if isinstance(translated_raw, str) else None
                    )
                    if translated:
                        indent = line[: len(line) - len(line.lstrip())]
                        ending = "\n" if line.endswith("\n") else ""
                        new_lines.append(f"{indent}{translated}{ending}")
                        modified = True
                    else:
                        new_lines.append(line)
                except Exception as exc:
                    logger.error("Error translating line in {}: {}", file_path, exc)
                    new_lines.append(line)
            else:
                new_lines.append(line)
        if modified:
            file_path.write_text("".join(new_lines), encoding="utf-8")
            return f"✓ Updated: {file_path}"
        return f"No changes: {file_path}"
    except Exception as exc:
        return f"Error processing {file_path}: {exc}"
def _collect_files(root):
    files = []
    for pattern in FILE_PATTERNS:
        for path in root.rglob(pattern):
            if _should_skip(path):
                continue
            if path.is_file():
                files.append(path)
    return files
def main(argv=None):
    _ = list(argv) if argv is not None else sys.argv[1:]
    cwd = Path(".")
    files_to_process = _collect_files(cwd)
    if not files_to_process:
        logger.info("No files found to process.")
        return 0
    logger.info("Starting processing of {} files...", len(files_to_process))
    with Pool(processes=POOL_SIZE) as pool:
        for message in pool.imap_unordered(process_file, files_to_process):
            logger.info("{}", message)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
