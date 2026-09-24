import json
import sys
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Any, Final
import langdetect
from deep_translator import GoogleTranslator
from loguru import logger

CHUNK_SIZE = 4500
MAX_WORKERS = 8
SKIP_DIRS = frozenset({"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"})
Chunk = tuple[int, int, str]
TranslationRecord = dict[str, Any]


def chunk_file(file_path, size=32768):
    chunks = []
    current_chunk = []
    current_size = 0
    start_line = 0
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            line_len = len(line)
            if current_size + line_len > size and current_chunk:
                chunks.append((start_line, i - 1, "".join(current_chunk)))
                current_chunk = [line]
                current_size = line_len
                start_line = i
            else:
                current_chunk.append(line)
                current_size += line_len
        if current_chunk:
            chunks.append((start_line, len(lines) - 1, "".join(current_chunk)))
    except Exception as exc:
        logger.error(f"Error chunking {file_path}: {exc}")
    return chunks


def detect_language(text):
    try:
        return langdetect.detect(text[:500])
    except Exception:
        return None


def translate_chunk(chunk_data, index):
    start_line, end_line, text = chunk_data
    if index > 0:
        time.sleep(1)
    lang = detect_language(text)
    if lang == "en":
        return {
            "chunk_id": f"{start_line}_{end_line}",
            "start_line": start_line,
            "end_line": end_line,
            "translated": text,
            "skipped": True,
        }
    try:
        translator = GoogleTranslator(source="auto", target="en")
        translated = translator.translate(text)
        return {
            "chunk_id": f"{start_line}_{end_line}",
            "start_line": start_line,
            "end_line": end_line,
            "translated": translated,
            "skipped": False,
        }
    except Exception as exc:
        logger.error(f"Error translating chunk {start_line}-{end_line}: {exc}")
        return None


def process_file(file_path):
    print(f"Processing: {file_path.name}")
    chunks = chunk_file(file_path)
    print(f"Total chunks: {len(chunks)}")
    translations = []
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(translate_chunk, (chunk, idx)) for idx, chunk in enumerate(chunks)]
        completed = 0
        for async_res in async_results:
            result = async_res.get()
            if result is not None:
                translations.append(result)
            completed += 1
            print(f"Progress ({file_path.name}): {completed}/{len(chunks)}")
    output_file = file_path.with_suffix(".json")
    try:
        output_data = {"lines": sorted(translations, key=lambda x: x["start_line"])}
        output_file.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ JSON output saved to: {output_file.name}")
    except Exception as exc:
        logger.error(f"Error saving JSON output for {file_path}: {exc}")


def get_input_files(paths):
    files = []
    search_paths = [Path(p) for p in paths] if paths else [Path.cwd()]
    for path in search_paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(path.rglob("*.txt"))
    return [f for f in files if not any(part in SKIP_DIRS for part in f.parts)]


def main():
    input_paths = sys.argv[1:]
    files = get_input_files(input_paths)
    if not files:
        print("No text files found to process.")
        return
    for file_path in files:
        try:
            process_file(file_path)
        except Exception as exc:
            logger.error(f"Unexpected error processing {file_path}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
