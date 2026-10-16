from __future__ import annotations

import logging
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator
from dh import get_nobinary

MAX_WORKERS: Final[int] = 4
MAX_RETRIES: Final[int] = 2
RETRY_DELAY: Final[float] = 3.0
NON_ENGLISH_PATTERN: Final[re.Pattern] = re.compile(r"[^\x00-\x7F]")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def is_english(text: str) -> bool:
    return not NON_ENGLISH_PATTERN.search(text)


def main() -> None:
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_nobinary(Path.cwd())
    if not files:
        logger.info("No files found to process.")
        return
    logger.info(f"Found {len(files)} files to process.")
    process_files_with_retry(files)


def process_file(path: Path) -> Path | None:
    logger.info(f"  Processing {path.name}...")
    try:
        original = path.read_text(encoding="utf-8", errors="ignore")
        if is_english(original):
            return None
        translated = translate_file_content(path)
        print(translated)
        if translated.strip() != original.strip():
            safe_overwrite(path, translated)
            logger.info(f"  ✓ Updated {path.name}")
        return None
    except Exception as e:
        logger.error(f"  Failed to process {path}: {e}")
        return path


def process_files_with_retry(files: list[Path]) -> None:
    files_to_process = files.copy()
    retry_count = 0
    while files_to_process and (retry_count < MAX_RETRIES):
        if retry_count > 0:
            logger.info(f"""{("=" * 40)}""")
            logger.info(f"Retry attempt {retry_count}/{MAX_RETRIES}")
            logger.info(f"Retrying {len(files_to_process)} failed files...")
            logger.info(f"""{("=" * 40)}""")
            time.sleep(RETRY_DELAY)
        failed_files = []
        with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_file, f): f for f in files_to_process}
            for future in as_completed(futures):
                f = futures[future]
                try:
                    failed = future.result()
                    if failed:
                        failed_files.append(failed)
                except Exception as e:
                    logger.error(f"File {f} generated an exception: {e}")
                    failed_files.append(f)
        files_to_process = failed_files
        retry_count += 1
        if failed_files:
            logger.warning(f"{len(failed_files)} files failed and will be retried.")
    if files_to_process:
        logger.error(f"""Failed to process {len(files_to_process)} files after {MAX_RETRIES} retries:""")
        for f in files_to_process:
            logger.error(f"  - {f}")


def safe_overwrite(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, dir=path.parent) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    shutil.move(tmp_path, path)


def translate_file_content(path: Path, retries: int = MAX_RETRIES) -> str:
    for attempt in range(retries):
        try:
            return GoogleTranslator(source="auto", target="en").translate_file(str(path))
        except Exception as e:
            if attempt < (retries - 1):
                logger.warning(
                    f"File translation attempt {(attempt + 1)} failed for {path}: {e}. Retrying in {RETRY_DELAY}s..."
                )
                time.sleep(RETRY_DELAY)
            else:
                logger.error(f"File translation failed after {retries} attempts for {path}: {e}")
                return path.read_text(encoding="utf-8", errors="ignore")


if __name__ == "__main__":
    raise SystemExit(main())
