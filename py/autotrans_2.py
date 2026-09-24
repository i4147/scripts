import re
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final
from deep_translator import GoogleTranslator
from dh import is_binary
from loguru import logger

DIRECTORY = "."
CHUNK_SIZE = 32768
MAX_WORKERS = 8
NON_ENGLISH_PATTERN = re.compile(r"[^\x00-\x7F]")
try:
    from fastwalk import walk_files as _walk_files

    _HAS_FASTWALK = True
except ImportError:
    _walk_files = None
    _HAS_FASTWALK = False


def split_into_chunks(text, size):
    return [text[i : i + size] for i in range(0, len(text), size)]


def translate_chunk(chunk):
    if not chunk.strip():
        return chunk
    try:
        translator = GoogleTranslator(source="auto", target="en")
        result = translator.translate(chunk)
        return result if result else chunk
    except Exception as exc:
        logger.error(f"Chunk translation failed: {exc}")
        return chunk


def contains_non_english(text):
    return bool(NON_ENGLISH_PATTERN.search(text))


def translate_file(path):
    print(f"Processing file: {path}")
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        logger.error(f"Cannot read file {path}: {exc}")
        return
    if not contains_non_english(content):
        print(f"File is already English: {path.name}")
        return
    print(f"Non-English content detected in: {path.name}")
    chunks = split_into_chunks(content, CHUNK_SIZE)
    print(f"Total chunks: {len(chunks)}. Translating...")
    translated_chunks = [translate_chunk(chunk) for chunk in chunks]
    translated_text = "".join(translated_chunks)
    new_path = path.with_stem(f"{path.stem}_eng")
    try:
        new_path.write_text(translated_text, encoding="utf-8")
        print(f"✓ Translated → {new_path.name}")
    except Exception as exc:
        logger.error(f"Failed to write output file {new_path}: {exc}")


def scan_files(directory):
    files = []
    if _HAS_FASTWALK and _walk_files is not None:
        walker = _walk_files
        for pth in walker(str(directory)):
            p = Path(pth)
            if p.is_file() and not is_binary(p):
                files.append(p)
    else:
        for p in directory.rglob("*"):
            if p.is_file() and not any(part.startswith(".") for part in p.parts) and not is_binary(p):
                files.append(p)
    return files


def process_directory(directory):
    print(f"Scanning directory: {directory}")
    dir_path = Path(directory)
    files = scan_files(dir_path)
    print(f"Total text files found: {len(files)}")
    if not files:
        return
    print("Starting parallel file translation...\n")
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(translate_file, (f,)) for f in files]
        for f, async_res in zip(files, async_results):
            try:
                async_res.get()
            except Exception as exc:
                logger.error(f"Unexpected error processing {f}: {exc}")


def main():
    process_directory(DIRECTORY)


if __name__ == "__main__":
    raise SystemExit(main())
