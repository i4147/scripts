from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Final, TypedDict

from deep_translator import GoogleTranslator

CHUNK_SIZE = 1024 * 1024
CHUNK_SIZE: Final[int] = 4500
MAX_WORKERS: Final[int] = 1
INPUT_FILE: Final[Path] = Path("words.txt")
OUTPUT_FILE: Final[Path] = Path("fa_en.json")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TranslationResult(TypedDict):
    chunk_id: str
    start_line: int
    end_line: int
    original: str
    translated: str


def chunk_file(path: Path, chunk_size: int = 32768) -> list[tuple[int, int, str]]:
    chunks = []
    current_chunk = []
    current_size = 0
    start_line = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f):
                if current_size + len(line) > chunk_size and current_chunk:
                    chunks.append((start_line, line_num - 1, "".join(current_chunk)))
                    current_chunk = [line]
                    current_size = len(line)
                    start_line = line_num
                else:
                    current_chunk.append(line)
                    current_size += len(line)
            if current_chunk:
                chunks.append((start_line, line_num, "".join(current_chunk)))
    except Exception as e:
        logger.error(f"Error reading file {path}: {e}")
    return chunks


def translate_chunk(chunk_data: tuple[int, int, str], chunk_index: int, total_chunks: int) -> TranslationResult | None:
    start_line, end_line, text = chunk_data
    if chunk_index > 0:
        time.sleep(2)
    try:
        translator = GoogleTranslator(source="fa", target="en")
        translated = translator.translate(text)
        if not translated:
            return None
        return {
            "chunk_id": f"{start_line}_{end_line}",
            "start_line": start_line,
            "end_line": end_line,
            "original": text,
            "translated": translated,
        }
    except Exception as e:
        logger.error(f"Error translating chunk {start_line}_{end_line}: {e}")
        return None


def main() -> None:
    if not INPUT_FILE.exists():
        logger.error(f"Input file {INPUT_FILE} not found.")
        return
    logger.info("Extracting chunks...")
    chunks = chunk_file(INPUT_FILE)
    logger.info(f"Total chunks: {len(chunks)}")
    if not chunks:
        logger.warning("No text found to translate.")
        return
    logger.info("Translating chunks...")
    translations: list[TranslationResult] = []
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(translate_chunk, chunk, idx, len(chunks)) for idx, chunk in enumerate(chunks)]
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                translations.append(result)
            logger.info(f"Progress: {i}/{len(chunks)}")
    if not translations:
        logger.warning("No translations were successful.")
        return
    logger.info(f"Writing results to {OUTPUT_FILE}...")
    try:
        final_data = {"translations": sorted(translations, key=lambda x: x["start_line"])}
        OUTPUT_FILE.write_text(json.dumps(final_data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Done!")
    except Exception as e:
        logger.error(f"Error writing output file: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
