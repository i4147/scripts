from __future__ import annotations

import json
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Final

import langdetect
from deep_translator import GoogleTranslator

CHUNK_SIZE = 1024 * 1024
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
CHUNK_SIZE: Final[int] = 4500
MAX_WORKERS: Final[int] = 3
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def chunk_file(path: Path, size: int = 32768) -> list[tuple[int, int, str]]:
    chunks: list[tuple[int, int, str]] = []
    current_chunk: list[str] = []
    current_size = 0
    start_line = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
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
    except Exception as e:
        logger.error("Error chunking %s: %s", path, e)
    return chunks


def detect_language(text: str) -> str | None:
    try:
        return langdetect.detect(text[:500])
    except Exception:
        return None


def translate_chunk(chunk_data: tuple[int, int, str], index: int) -> dict[str, Any] | None:
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
    except Exception as e:
        logger.error("Error translating chunk %d-%d: %s", start_line, end_line, e)
        return None


def process_file(path: Path) -> None:
    logger.info("Processing: %s", path.name)
    chunks = chunk_file(path)
    logger.info("Total chunks: %d", len(chunks))
    translations: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_chunk = {executor.submit(translate_chunk, chunk, idx): idx for idx, chunk in enumerate(chunks)}
        completed = 0
        for future in as_completed(future_to_chunk):
            if result := future.result():
                translations.append(result)
            completed += 1
            logger.info("Progress (%s): %d/%d", path.name, completed, len(chunks))
    output_file = path.with_suffix(".json")
    try:
        output_data = {"lines": sorted(translations, key=lambda x: x["start_line"])}
        output_file.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("✓ JSON output saved to: %s", output_file.name)
    except Exception as e:
        logger.error("Error saving JSON output for %s: %s", path, e)


def get_input_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    search_paths = [Path(p) for p in paths] if paths else [Path.cwd()]
    for path in search_paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(path.rglob("*.txt"))
    return [f for f in files if not any(part in SKIP_DIRS for part in f.parts)]


def main() -> None:
    input_paths = sys.argv[1:]
    files = get_input_files(input_paths)
    if not files:
        logger.info("No text files found to process.")
        return
    for path in files:
        try:
            process_file(path)
        except Exception as e:
            logger.error("Unexpected error processing %s: %s", path, e)


if __name__ == "__main__":
    raise SystemExit(main())
