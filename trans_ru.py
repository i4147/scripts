import json
import random
import re
import sys
import time
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Final
from deep_translator import GoogleTranslator
from loguru import logger
MAX_WORKERS = 8
RETRY_ATTEMPTS = 4
RETRY_DELAY = 0.6
MAX_CHUNK_SIZE = 2000
CYRILLIC_PATTERN = re.compile(
    r"[\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F\u1C80-\u1C8F]"
)
def contains_cyrillic(text):
    return bool(CYRILLIC_PATTERN.search(text))
def create_chunks(lines):
    chunks = []
    current_chunk = []
    current_size = 0
    for line in lines:
        line_size = len(line) + 1
        if line_size > MAX_CHUNK_SIZE:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0
            chunks.append([line])
            continue
        if current_size + line_size > MAX_CHUNK_SIZE and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        current_chunk.append(line)
        current_size += line_size
    if current_chunk:
        chunks.append(current_chunk)
    return chunks
def _translate_lines_individually(lines):
    translations = {}
    for line in lines:
        try:
            translated = GoogleTranslator(source="ru", target="en").translate(line)
            translations[line] = translated if translated is not None else line
        except Exception as exc:
            logger.error("Per-line fallback failed for '{}': {}", line[:50], exc)
            translations[line] = line
    return translations
def translate_chunk(chunk):
    chunk_text = "\n".join(chunk)
    translator = GoogleTranslator(source="ru", target="en")
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            translated = translator.translate(chunk_text)
            if translated is not None:
                return (chunk, translated)
        except Exception as exc:
            delay = RETRY_DELAY * (2 ** (attempt - 1))
            jitter = random.uniform(0, delay * 0.25)
            sleep_time = delay + jitter
            logger.warning(
                "Translate attempt {}/{} failed for chunk starting '{}...': {}. Retrying in {:.2f}s",
                attempt,
                RETRY_ATTEMPTS,
                (chunk[0][:60] + "...") if chunk else "",
                exc,
                sleep_time,
            )
            if attempt < RETRY_ATTEMPTS:
                time.sleep(sleep_time)
    return (chunk, None)
def _read_lines(input_path):
    try:
        with input_path.open(encoding="utf-8") as handle:
            return [raw.rstrip("\n") for raw in handle if raw.strip() != ""]
    except Exception as exc:
        logger.error("Error reading input file: {}", exc)
        return None
def _dedupe_preserving_order(lines):
    seen = set()
    unique = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique
def _merge_chunk_result(
    original_lines,
    translated_text,
    results,
    completed,
    total,
):
    if not translated_text:
        logger.error(
            "Failed to translate chunk starting with: {}",
            (original_lines[0][:60] + "...") if original_lines else "",
        )
        return
    translated_lines = translated_text.splitlines()
    if len(translated_lines) == len(original_lines):
        for i, original_line in enumerate(original_lines):
            results[original_line] = translated_lines[i]
    else:
        logger.warning(
            "Line-count mismatch in chunk ({} original vs {} translated). "
            "Falling back to per-line translation for this chunk.",
            len(original_lines),
            len(translated_lines),
        )
        results.update(_translate_lines_individually(original_lines))
    sample_original = original_lines[0] if original_lines else ""
    print(
        "Translated chunk {}/{} (sample: '{}' → '{}')",
        completed,
        total,
        sample_original[:40] + ("..." if len(sample_original) > 40 else ""),
        results.get(sample_original, "")[:60],
    )
def _save_json(results, output_path):
    try:
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)
        print("Saved {} translations to {}", len(results), output_path.name)
    except Exception as exc:
        logger.error("Error saving JSON file: {}", exc)
def _rewrite_input_file(input_path, all_lines, results):
    try:
        with input_path.open("w", encoding="utf-8") as handle:
            translated_count = 0
            for line in all_lines:
                if line in results:
                    handle.write(f"{results[line]}\n")
                    translated_count += 1
                else:
                    handle.write(f"{line}\n")
        print(
            "Updated {}: translated {} lines, kept {} lines unchanged",
            input_path.name,
            translated_count,
            len(all_lines) - translated_count,
        )
    except Exception as exc:
        logger.error("Error updating input file: {}", exc)
def main():
    if len(sys.argv) < 2:
        logger.error("Usage: {} <input_file.txt>", sys.argv[0])
        return 1
    input_path = Path(sys.argv[1].strip())
    if not input_path.exists():
        logger.error("Input file not found: {}", input_path)
        return 1
    all_lines = _read_lines(input_path)
    if all_lines is None:
        return 1
    if not all_lines:
        print("No non-empty lines found in {}", input_path.name)
        return 0
    russian_lines_raw = [line for line in all_lines if contains_cyrillic(line)]
    non_russian_count = len(all_lines) - len(russian_lines_raw)
    print(
        "Loaded {} lines: {} with Cyrillic, {} already non-Cyrillic/skipped",
        len(all_lines),
        len(russian_lines_raw),
        non_russian_count,
    )
    if not russian_lines_raw:
        print("No Russian/Cyrillic lines to translate in {}", input_path.name)
        return 0
    russian_lines = _dedupe_preserving_order(russian_lines_raw)
    print(
        "Deduplicated Russian lines: {} unique from {} total",
        len(russian_lines),
        len(russian_lines_raw),
    )
    chunks = create_chunks(russian_lines)
    if not chunks:
        print("Nothing to translate after chunking.")
        return 0
    print(
        "Created {} chunk(s) from {} unique Russian lines (max {} chars per "
        "chunk), using {} worker(s)",
        len(chunks),
        len(russian_lines),
        MAX_CHUNK_SIZE,
        MAX_WORKERS,
    )
    results = {}
    total = len(chunks)
    completed = 0
    pool = Pool(processes=MAX_WORKERS)
    try:
        async_results = [
            pool.apply_async(translate_chunk, (chunk,)) for chunk in chunks
        ]
        for async_result in async_results:
            completed += 1
            chunk_for_log = chunks[completed - 1]
            try:
                original_lines, translated_text = async_result.get()
                _merge_chunk_result(
                    original_lines,
                    translated_text,
                    results,
                    completed,
                    total,
                )
            except Exception as exc:
                logger.error(
                    "Unexpected error processing chunk starting with '{}': {}",
                    (chunk_for_log[0][:60] + "...") if chunk_for_log else "",
                    exc,
                )
    finally:
        pool.close()
        pool.join()
    output_path = input_path.with_suffix(".json")
    _save_json(results, output_path)
    _rewrite_input_file(input_path, all_lines, results)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
