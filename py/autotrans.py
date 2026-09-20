from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator
from dh import is_binary

DIRECTORY: Final[str] = "."
CHUNK_SIZE: Final[int] = 2000
MAX_WORKERS_FILE: Final[int] = 6
MAX_WORKERS_CHUNK: Final[int] = 8
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
try:
    from fastwalk import walk_files

    HAS_FASTWALK = True
except ImportError:
    HAS_FASTWALK = False
NON_ENGLISH_PATTERN: Final[re.Pattern] = re.compile(r"[^\x00-\x7F]")


def split_into_chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def translate_chunk(chunk: str) -> str:
    if not chunk.strip():
        return chunk
    try:
        return GoogleTranslator(source="auto", target="en").translate(chunk)
    except Exception as e:
        logger.error("Chunk translation failed: %s", e)
        return chunk


def contains_non_english(text: str) -> bool:
    return bool(NON_ENGLISH_PATTERN.search(text))


def translate_file(path: Path) -> None:
    logger.info("Processing file: %s", path)
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.error("Cannot read file %s: %s", path, e)
        return
    if not contains_non_english(content):
        logger.info("File is already English: %s", path.name)
        return
    logger.info("Non-English content detected in: %s", path.name)
    chunks = split_into_chunks(content, 32768)
    logger.info("Total chunks: %d. Translating in parallel...", len(chunks))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS_CHUNK) as executor:
        translated_chunks = list(executor.map(translate_chunk, chunks))
    translated_text = "".join(translated_chunks)
    new_path = path.with_stem(f"{path.stem}_eng")
    try:
        new_path.write_text(translated_text, encoding="utf-8")
        logger.info("✓ Translated → %s", new_path.name)
    except Exception as e:
        logger.error("Failed to write output file %s: %s", new_path, e)


def process_directory(directory: str) -> None:
    logger.info("Scanning directory: %s", directory)
    dir_path = Path(directory)
    files: list[Path] = []
    if HAS_FASTWALK:
        for pth in walk_files(directory):
            p = Path(pth)
            if p.is_file() and (not is_binary(p)):
                files.append(p)
    else:
        for p in dir_path.rglob("*"):
            if p.is_file() and (not any(part.startswith(".") for part in p.parts)) and (not is_binary(p)):
                files.append(p)
    logger.info("Total text files found: %d", len(files))
    if not files:
        return
    logger.info("Starting parallel file translation...\n")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS_FILE) as executor:
        futures = {executor.submit(translate_file, f): f for f in files}
        for future in as_completed(futures):
            f = futures[future]
            try:
                future.result()
            except Exception as e:
                logger.error("Unexpected error processing %s: %s", f, e)


if __name__ == "__main__":
    process_directory(DIRECTORY)
