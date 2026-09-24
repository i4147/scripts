import re
import sys
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final
from deep_translator import GoogleTranslator
from loguru import logger

CHUNK_SIZE = 4500
MAX_WORKERS = 8
CHUNK_DELAY = 1.5
FILE_DELAY = 2.0
TARGET_SUFFIXES = frozenset({".txt", ".md", ".py", ".json", ".csv"})
SKIP_DIRS = frozenset({"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"})
PERSIAN_PATTERN = re.compile("[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")
BOUNDARY_PATTERN = re.compile(r"[\s\n\.\!\?\;]+")


def split_into_chunks(text, size=4900):
    if len(text) <= size:
        return [text]
    chunks = []
    pos = 0
    while pos < len(text):
        end = min(pos + size, len(text))
        if end == len(text):
            chunks.append(text[pos:])
            break
        boundary_match = None
        for match in BOUNDARY_PATTERN.finditer(text, pos, end):
            boundary_match = match
        if boundary_match is not None and boundary_match.end() > pos:
            split_pos = boundary_match.end()
        else:
            split_pos = end
        chunks.append(text[pos:split_pos])
        pos = split_pos
    return chunks


def translate_chunk(chunk):
    if not PERSIAN_PATTERN.search(chunk):
        return chunk
    try:
        translator = GoogleTranslator(source="fa", target="en")
        result = translator.translate(chunk)
        if result:
            print(f"Chunk translated: {result[:30].replace(chr(10), ' ')}...")
            time.sleep(CHUNK_DELAY)
            return result
        return chunk
    except Exception as exc:
        logger.error(f"Chunk translation error: {exc}")
        return chunk


def translate_file(path):
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(f"Skipping unreadable file {path}: {exc}")
        return
    if not PERSIAN_PATTERN.search(content):
        return
    print(f"Translating: {path.name}")
    chunks = split_into_chunks(content)
    translated_chunks = []
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(translate_chunk, (chunk,)) for chunk in chunks]
        for async_res in async_results:
            translated_chunks.append(async_res.get())
    translated_text = "".join(translated_chunks)
    try:
        path.write_text(translated_text, encoding="utf-8")
        print(f"✓ Updated: {path.name}")
    except Exception as exc:
        logger.error(f"Error writing to {path}: {exc}")
    time.sleep(FILE_DELAY)


def get_files(path):
    files = []
    for p in path.rglob("*"):
        if any(part.startswith(".") or part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in TARGET_SUFFIXES:
            files.append(p)
    return sorted(files)


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else "."
    start_path = Path(directory)
    if not start_path.exists():
        logger.error(f"Path does not exist: {directory}")
        sys.exit(1)
    files = get_files(start_path)
    if not files:
        print("No files found to process.")
        return
    print(f"Processing {len(files)} files...")
    for f in files:
        translate_file(f)


if __name__ == "__main__":
    raise SystemExit(main())
