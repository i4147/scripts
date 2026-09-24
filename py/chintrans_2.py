import re
import sys
import time
from multiprocessing import Pool
from pathlib import Path
from typing import Final
from deep_translator import GoogleTranslator
from loguru import logger

POOL_WORKERS = 8
RETRY_ATTEMPTS = 3
RETRY_DELAY = 0.5
MAX_CHUNK_SIZE = 5000
CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


def contains_chinese(text):
    return bool(CHINESE_PATTERN.search(text))


def create_chunks(lines):
    chunks = []
    current_chunk = []
    current_size = 0
    for line in lines:
        line_size = len(line) + 1
        if current_size + line_size > MAX_CHUNK_SIZE and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        if line_size > MAX_CHUNK_SIZE:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0
            chunks.append([line])
        else:
            current_chunk.append(line)
            current_size += line_size
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def translate_chunk(chunk):
    chunk_text = "\n".join(chunk)
    translator = GoogleTranslator(source="auto", target="en")
    for attempt in range(RETRY_ATTEMPTS):
        try:
            result = translator.translate(chunk_text)
            if result:
                return (chunk, result)
        except Exception as e:
            logger.warning(
                "Failed chunk starting with '{}' (attempt {}/{}): {}",
                chunk[0][:50],
                attempt + 1,
                RETRY_ATTEMPTS,
                e,
            )
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    return (chunk, None)


def main():
    if len(sys.argv) < 2:
        logger.error("Usage: {} <input_file>", Path(sys.argv[0]).name)
        return
    input_path = Path(sys.argv[1].strip())
    if not input_path.exists():
        logger.error("Input file not found: {}", input_path.name)
        return
    try:
        with input_path.open(encoding="utf-8") as f:
            all_lines = [w.strip() for w in f if w.strip()]
    except Exception as e:
        logger.error("Error reading input file: {}", e)
        return
    if not all_lines:
        print("No lines found in {}", input_path.name)
        return
    chinese_lines = [line for line in all_lines if contains_chinese(line)]
    non_chinese_lines = [line for line in all_lines if not contains_chinese(line)]
    print(
        "Loaded {} lines: {} with Chinese, {} already English/skipped",
        len(all_lines),
        len(chinese_lines),
        len(non_chinese_lines),
    )
    if not chinese_lines:
        print("No Chinese lines to translate in {}", input_path.name)
        return
    chunks = create_chunks(chinese_lines)
    print(
        "Created {} chunks from {} Chinese lines (max {} chars per chunk)",
        len(chunks),
        len(chinese_lines),
        MAX_CHUNK_SIZE,
    )
    results = {}
    with Pool(processes=POOL_WORKERS) as pool:
        async_results = [pool.apply_async(translate_chunk, (chunk,)) for chunk in chunks]
        for async_result, chunk in zip(async_results, chunks):
            try:
                original_lines, translated_text = async_result.get()
                if translated_text:
                    translated_lines = translated_text.split("\n")
                    for i, original_line in enumerate(original_lines):
                        if i < len(translated_lines):
                            results[original_line] = translated_lines[i]
                            print("{} → {}", original_line, translated_lines[i])
                        else:
                            logger.error(
                                "Line count mismatch in chunk, missing translation for: {}",
                                original_line,
                            )
                else:
                    logger.error("Failed to translate chunk starting with: {}", chunk[0][:50])
            except Exception as e:
                logger.error(
                    "Unexpected error for chunk starting with '{}': {}",
                    chunk[0][:50],
                    e,
                )
    try:
        with input_path.open("w", encoding="utf-8") as f:
            for line in all_lines:
                if line in results:
                    f.write(f"{results[line]}\n")
                else:
                    f.write(f"{line}\n")
        print(
            "Updated {}: translated {} lines, kept {} lines unchanged",
            input_path.name,
            len(results),
            len(non_chinese_lines),
        )
    except Exception as e:
        logger.error("Error updating input file: {}", e)


if __name__ == "__main__":
    raise SystemExit(main())
