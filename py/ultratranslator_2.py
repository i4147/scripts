import re
import shutil
import sys
import tempfile
import time
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final
from deep_translator import GoogleTranslator
from dh import get_nobinary
from loguru import logger

MAX_WORKERS = 8
MAX_RETRIES = 2
RETRY_DELAY = 3.0
NON_ENGLISH_PATTERN = re.compile(r"[^\x00-\x7F]")


def is_english(text):
    return not NON_ENGLISH_PATTERN.search(text)


def safe_overwrite(filepath, content):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, dir=str(filepath.parent)) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    shutil.move(str(tmp_path), str(filepath))


def translate_file_content(path, retries=MAX_RETRIES):
    for attempt in range(retries):
        try:
            translator = GoogleTranslator(source="auto", target="en")
            result = translator.translate_file(str(path))
            return result if result is not None else path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            if attempt < (retries - 1):
                logger.warning(
                    f"File translation attempt {attempt + 1} failed for {path}: {exc}. Retrying in {RETRY_DELAY}s..."
                )
                time.sleep(RETRY_DELAY)
            else:
                logger.error(f"File translation failed after {retries} attempts for {path}: {exc}")
                return path.read_text(encoding="utf-8", errors="ignore")
    return path.read_text(encoding="utf-8", errors="ignore")


def process_file(path):
    print(f"  Processing {path.name}...")
    try:
        original = path.read_text(encoding="utf-8", errors="ignore")
        if is_english(original):
            return None
        translated = translate_file_content(path)
        logger.debug(translated)
        if translated.strip() != original.strip():
            safe_overwrite(path, translated)
            print(f"  ✓ Updated {path.name}")
        return None
    except Exception as exc:
        logger.error(f"  Failed to process {path}: {exc}")
        return path


def process_files_with_retry(files):
    files_to_process = list(files)
    retry_count = 0
    while files_to_process and retry_count < MAX_RETRIES:
        if retry_count > 0:
            print("=" * 40)
            print(f"Retry attempt {retry_count}/{MAX_RETRIES}")
            print(f"Retrying {len(files_to_process)} failed files...")
            print("=" * 40)
            time.sleep(RETRY_DELAY)
        failed_files = []
        with Pool(processes=MAX_WORKERS) as pool:
            async_results = [pool.apply_async(process_file, (f,)) for f in files_to_process]
            for f, async_res in zip(files_to_process, async_results):
                try:
                    failed = async_res.get()
                    if failed is not None:
                        failed_files.append(failed)
                except Exception as exc:
                    logger.error(f"File {f} generated an exception: {exc}")
                    failed_files.append(f)
        files_to_process = failed_files
        retry_count += 1
        if failed_files:
            logger.warning(f"{len(failed_files)} files failed and will be retried.")
    if files_to_process:
        logger.error(f"Failed to process {len(files_to_process)} files after {MAX_RETRIES} retries:")
        for f in files_to_process:
            logger.error(f"  - {f}")


def main():
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else list(get_nobinary(Path.cwd()))
    if not files:
        print("No files found to process.")
        return
    print(f"Found {len(files)} files to process.")
    process_files_with_retry(files)


if __name__ == "__main__":
    raise SystemExit(main())
