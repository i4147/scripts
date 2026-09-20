from __future__ import annotations

import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator

CHUNK_SIZE = 1024 * 1024

CHUNK_SIZE: Final[int] = 4500
MAX_WORKERS: Final[int] = 16
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
NON_ASCII_PATTERN: Final[re.Pattern] = re.compile("[^\\x00-\\x7F]")
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def split_into_chunks(text: str, size: int = 4900) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def translate_chunk(chunk: str) -> str:
    if not NON_ASCII_PATTERN.search(chunk):
        return chunk
    try:
        translator = GoogleTranslator(source="auto", target="en")
        result = translator.translate(chunk)
        if result:
            logger.info("Chunk translated: %s...", result[:30].replace("\n", " "))
            return result
        return chunk
    except Exception as e:
        logger.error("Chunk translation error: %s", e)
        return chunk


def translate_file(path: Path) -> None:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Skipping unreadable file %s: %s", path, e)
        return
    if not NON_ASCII_PATTERN.search(content):
        return
    logger.info("Translating: %s", path.name)
    chunks = split_into_chunks(content)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        translated_chunks = list(executor.map(translate_chunk, chunks))
    translated_text = "".join(translated_chunks)
    try:
        path.write_text(translated_text, encoding="utf-8")
        logger.info("✓ Updated: %s", path.name)
    except Exception as e:
        logger.error("Error writing to %s: %s", path, e)


def get_files(path: Path) -> list[Path]:
    files: list[Path] = []
    for p in path.rglob("*"):
        if any(part.startswith(".") or part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in {".txt", ".md", ".py", ".json", ".csv"}:
            files.append(p)
    return sorted(files)


def main() -> None:
    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    start_path = Path(directory)
    if not start_path.exists():
        logger.error("Path does not exist: %s", directory)
        sys.exit(1)
    files = get_files(start_path)
    if not files:
        logger.info("No files found to process.")
        return
    logger.info("Processing %d files...", len(files))
    for f in files:
        translate_file(f)


if __name__ == "__main__":
    main()
