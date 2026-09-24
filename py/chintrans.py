from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator

MAX_WORKERS: Final[int] = 16
RETRY_ATTEMPTS: Final[int] = 3
RETRY_DELAY: Final[float] = 0.5
MAX_CHUNK_SIZE: Final[int] = 5000
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]", text))


def create_chunks(lines: list[str]) -> list[list[str]]:
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


def translate_chunk(chunk: list[str]) -> tuple[list[str], str | None]:
    chunk_text = "\n".join(chunk)
    translator = GoogleTranslator(source="auto", target="en")
    for attempt in range(RETRY_ATTEMPTS):
        try:
            result = translator.translate(chunk_text)
            if result:
                return (chunk, result)
        except Exception as e:
            logger.warning(
                "Failed chunk starting with '%s' (attempt %d/%d): %s",
                chunk[0][:50],
                attempt + 1,
                RETRY_ATTEMPTS,
                e,
            )
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    return (chunk, None)


def main() -> None:
    import sys

    input_path = Path(sys.argv[1].strip())
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path.name)
        return
    try:
        with input_path.open(encoding="utf-8") as f:
            all_lines = [w.strip() for w in f if w.strip()]
    except Exception as e:
        logger.error("Error reading input file: %s", e)
        return
    if not all_lines:
        logger.info("No lines found in %s", input_path.name)
        return
    chinese_lines = [line for line in all_lines if contains_chinese(line)]
    non_chinese_lines = [line for line in all_lines if not contains_chinese(line)]
    logger.info(
        "Loaded %d lines: %d with Chinese, %d already English/skipped",
        len(all_lines),
        len(chinese_lines),
        len(non_chinese_lines),
    )
    if not chinese_lines:
        logger.info("No Chinese lines to translate in %s", input_path.name)
        return
    chunks = create_chunks(chinese_lines)
    logger.info(
        "Created %d chunks from %d Chinese lines (max %d chars per chunk)",
        len(chunks),
        len(chinese_lines),
        MAX_CHUNK_SIZE,
    )
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_chunk = {executor.submit(translate_chunk, chunk): chunk for chunk in chunks}
        for future in as_completed(future_to_chunk):
            chunk = future_to_chunk[future]
            try:
                original_lines, translated_text = future.result()
                if translated_text:
                    translated_lines = translated_text.split("\n")
                    for i, original_line in enumerate(original_lines):
                        if i < len(translated_lines):
                            results[original_line] = translated_lines[i]
                            print(f"{original_line} → {translated_lines[i]}")
                        else:
                            logger.error(
                                "Line count mismatch in chunk, missing translation for: %s",
                                original_line,
                            )
                else:
                    logger.error("Failed to translate chunk starting with: %s", chunk[0][:50])
            except Exception as e:
                logger.error(
                    "Unexpected error for chunk starting with '%s': %s",
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
        logger.info(
            "Updated %s: translated %d lines, kept %d lines unchanged",
            input_path.name,
            len(results),
            len(non_chinese_lines),
        )
    except Exception as e:
        logger.error("Error updating input file: %s", e)


if __name__ == "__main__":
    raise SystemExit(main())
