from __future__ import annotations

import json
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator

MAX_WORKERS: Final[int] = 16
RETRY_ATTEMPTS: Final[int] = 4
RETRY_DELAY: Final[float] = 0.6
MAX_CHUNK_SIZE: Final[int] = 2000
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def contains_cyrillic(text: str) -> bool:
    return bool(
        re.search(
            r"[\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F\u1C80-\u1C8F]",
            text,
        )
    )


def create_chunks(lines: list[str]) -> list[list[str]]:
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
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


def translate_chunk(chunk: list[str]) -> tuple[list[str], str | None]:
    chunk_text = "\n".join(chunk)
    translator = GoogleTranslator(source="ru", target="en")
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            translated = translator.translate(chunk_text)
            if translated is not None:
                return (chunk, translated)
        except Exception as e:
            delay = RETRY_DELAY * (2 ** (attempt - 1))
            jitter = random.uniform(0, delay * 0.25)
            sleep_time = delay + jitter
            logger.warning(
                "Translate attempt %d/%d failed for chunk starting '%s...': %s. Retrying in %.2fs",
                attempt,
                RETRY_ATTEMPTS,
                (chunk[0][:60] + "...") if chunk else "",
                e,
                sleep_time,
            )
            if attempt < RETRY_ATTEMPTS:
                time.sleep(sleep_time)
    return (chunk, None)


def main() -> None:
    import sys

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input_file.txt>")
        return
    input_path = Path(sys.argv[1].strip())
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        return
    try:
        with input_path.open(encoding="utf-8") as f:
            all_lines = [w.rstrip("\n") for w in f if w.strip() != ""]
    except Exception as e:
        logger.error("Error reading input file: %s", e)
        return
    if not all_lines:
        logger.info("No non-empty lines found in %s", input_path.name)
        return
    russian_lines_raw = [line for line in all_lines if contains_cyrillic(line)]
    non_russian_lines = [line for line in all_lines if not contains_cyrillic(line)]
    logger.info(
        "Loaded %d lines: %d with Cyrillic, %d already non-Cyrillic/skipped",
        len(all_lines),
        len(russian_lines_raw),
        len(non_russian_lines),
    )
    if not russian_lines_raw:
        logger.info("No Russian/Cyrillic lines to translate in %s", input_path.name)
        return
    seen: set[str] = set()
    russian_lines: list[str] = []
    for l in russian_lines_raw:
        if l not in seen:
            seen.add(l)
            russian_lines.append(l)
    logger.info(
        "Deduplicated Russian lines: %d unique from %d total",
        len(russian_lines),
        len(russian_lines_raw),
    )
    chunks = create_chunks(russian_lines)
    num_workers = min(MAX_WORKERS, len(chunks)) if chunks else 1
    logger.info(
        "Created %d chunk(s) from %d unique Russian lines (max %d chars per chunk), using %d worker(s)",
        len(chunks),
        len(russian_lines),
        MAX_CHUNK_SIZE,
        num_workers,
    )
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        future_to_chunk = {executor.submit(translate_chunk, chunk): chunk for chunk in chunks}
        completed = 0
        total = len(future_to_chunk)
        for future in as_completed(future_to_chunk):
            chunk = future_to_chunk[future]
            completed += 1
            try:
                original_lines, translated_text = future.result()
                if translated_text:
                    translated_lines = translated_text.splitlines()
                    if len(translated_lines) == len(original_lines):
                        for i, original_line in enumerate(original_lines):
                            results[original_line] = translated_lines[i]
                    else:
                        logger.warning(
                            "Line-count mismatch in chunk (%d original vs %d translated). Falling back to per-line translation for this chunk.",
                            len(original_lines),
                            len(translated_lines),
                        )
                        for line in original_lines:
                            try:
                                t = GoogleTranslator(source="ru", target="en").translate(line)
                                results[line] = t if t is not None else line
                            except Exception as e:
                                logger.error(
                                    "Per-line fallback failed for '%s': %s",
                                    line[:50],
                                    e,
                                )
                                results[line] = line
                    logger.info(
                        "Translated chunk %d/%d (sample: '%s' → '%s')",
                        completed,
                        total,
                        original_lines[0][:40] + ("..." if len(original_lines[0]) > 40 else ""),
                        results.get(original_lines[0], "")[:60],
                    )
                else:
                    logger.error(
                        "Failed to translate chunk starting with: %s",
                        (chunk[0][:60] + "...") if chunk else "",
                    )
            except Exception as e:
                logger.error(
                    "Unexpected error processing chunk starting with '%s': %s",
                    (chunk[0][:60] + "...") if chunk else "",
                    e,
                )
    output_path = input_path.with_suffix(".json")
    try:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info("Saved %d translations to %s", len(results), output_path.name)
    except Exception as e:
        logger.error("Error saving JSON file: %s", e)
    try:
        with input_path.open("w", encoding="utf-8") as f:
            translated_count = 0
            for line in all_lines:
                if line in results:
                    f.write(f"{results[line]}\n")
                    translated_count += 1
                else:
                    f.write(f"{line}\n")
        logger.info(
            "Updated %s: translated %d lines, kept %d lines unchanged",
            input_path.name,
            translated_count,
            len(all_lines) - translated_count,
        )
    except Exception as e:
        logger.error("Error updating input file: %s", e)


if __name__ == "__main__":
    raise SystemExit(main())
