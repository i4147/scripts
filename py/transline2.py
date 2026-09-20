from __future__ import annotations

import logging
import re
import shutil
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator
from dh import get_files

NON_ENGLISH_PATTERN: Final[re.Pattern] = re.compile(r"[^\x00-\x7F]")
MAX_WORKERS: Final[int] = 4
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def is_english(text: str) -> bool:
    return not NON_ENGLISH_PATTERN.search(text)


def get_files(path: Path, include_hidden: bool = True, extensions: tuple[str, ...] | None = None) -> list[Path]:
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")
    files: list[Path] = []
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
            logger.warning("Permission denied: %s", current)
            continue
    return sorted(files)


def translate_text(text: str) -> str:
    if not text:
        return text
    lines = text.splitlines(keepends=True)
    translated_lines: list[str] = []
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
                logger.error("Translation error on line: %s", e)
                translated_lines.append(line)
    return "".join(translated_lines)


def safe_overwrite(filepath: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, dir=filepath.parent) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        shutil.move(tmp_path, filepath)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to overwrite {filepath}: {e}") from e


def process_file(path: Path) -> str:
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


def main() -> None:
    args = sys.argv[1:]
    cwd = Path.cwd()
    if args:
        files = [Path(p) for p in args if Path(p).is_file()]
    else:
        files = get_files(cwd, extensions=(".md", ".txt"))
    if not files:
        logger.info("No files found to process.")
        return
    logger.info("Starting processing of %d files...", len(files))
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_file = {executor.submit(process_file, f): f for f in files}
        for future in as_completed(future_to_file):
            result = future.result()
            logger.info(result)


if __name__ == "__main__":
    raise SystemExit(main())
