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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]", text))


def translate_line(line: str) -> str | None:
    translator = GoogleTranslator(source="auto", target="en")
    for attempt in range(RETRY_ATTEMPTS):
        try:
            result = translator.translate(line)
            if result:
                return result
        except Exception as e:
            logger.warning("Failed '%s' (attempt %d/%d): %s", line, attempt + 1, RETRY_ATTEMPTS, e)
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    return None


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
    logger.info("Starting translation with %d workers...", MAX_WORKERS)
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_line = {executor.submit(translate_line, line): line for line in chinese_lines}
        for future in as_completed(future_to_line):
            chinese_line = future_to_line[future]
            try:
                english_line = future.result()
                if english_line:
                    results[chinese_line] = english_line
                    print(f"{chinese_line} → {english_line}")
                else:
                    logger.error("Could not translate: %s", chinese_line)
            except Exception as e:
                logger.error("Unexpected error for '%s': %s", chinese_line, e)
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
