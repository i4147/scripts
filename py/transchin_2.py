import re
import sys
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final
from deep_translator import GoogleTranslator
from loguru import logger

MAX_WORKERS = 8
RETRY_ATTEMPTS = 3
RETRY_DELAY = 0.5
CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
TranslateResult = tuple[str, str | None]


def contains_chinese(text):
    return bool(CHINESE_PATTERN.search(text))


def translate_line(line):
    translator = GoogleTranslator(source="auto", target="en")
    for attempt in range(RETRY_ATTEMPTS):
        try:
            result = translator.translate(line)
            if result:
                return line, result
        except Exception as exc:
            logger.warning(f"Failed '{line}' (attempt {attempt + 1}/{RETRY_ATTEMPTS}): {exc}")
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY)
    return line, None


def main():
    if len(sys.argv) < 2:
        logger.error("Usage: script.py INPUT_FILE")
        sys.exit(1)
    input_path = Path(sys.argv[1].strip())
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path.name}")
        return
    try:
        with input_path.open(encoding="utf-8") as f:
            all_lines = [w.strip() for w in f if w.strip()]
    except Exception as exc:
        logger.error(f"Error reading input file: {exc}")
        return
    if not all_lines:
        print(f"No lines found in {input_path.name}")
        return
    chinese_lines = [line for line in all_lines if contains_chinese(line)]
    non_chinese_lines = [line for line in all_lines if not contains_chinese(line)]
    print(
        f"Loaded {len(all_lines)} lines: {len(chinese_lines)} with Chinese, "
        f"{len(non_chinese_lines)} already English/skipped"
    )
    if not chinese_lines:
        print(f"No Chinese lines to translate in {input_path.name}")
        return
    print(f"Starting translation with {MAX_WORKERS} workers...")
    results = {}
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(translate_line, (line,)) for line in chinese_lines]
        for chinese_line, async_res in zip(chinese_lines, async_results):
            try:
                _, english_line = async_res.get()
                if english_line:
                    results[chinese_line] = english_line
                    print(f"{chinese_line} → {english_line}")
                else:
                    logger.error(f"Could not translate: {chinese_line}")
            except Exception as exc:
                logger.error(f"Unexpected error for '{chinese_line}': {exc}")
    try:
        with input_path.open("w", encoding="utf-8") as f:
            for line in all_lines:
                if line in results:
                    f.write(f"{results[line]}\n")
                else:
                    f.write(f"{line}\n")
        print(
            f"Updated {input_path.name}: translated {len(results)} lines, kept {len(non_chinese_lines)} lines unchanged"
        )
    except Exception as exc:
        logger.error(f"Error updating input file: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
