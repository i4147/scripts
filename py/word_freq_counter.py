from __future__ import annotations

import json
import logging
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from dh import get_nobinary

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def process_file(file_path: Path) -> Counter:
    word_counter = Counter()
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        words = re.findall(r"\b[a-z]+\b", content.lower())
        word_counter.update(words)
        logger.debug(f"Processed {file_path.name}: {len(words)} words found")
    except Exception as e:
        logger.warning(f"Failed to process {file_path}: {e}")
    return word_counter


def collect_text_files(directory: Path | None = None) -> list[Path]:
    if directory is None:
        directory = Path.cwd()
    text_files = get_nobinary(directory)
    logger.info(f"Found {len(text_files)} text files to process")
    return text_files


def process_files_parallel(file_paths: list[Path], max_workers: int | None = None) -> Counter:
    total_counter = Counter()
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(process_file, file_path): file_path for file_path in file_paths}
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                file_counter = future.result()
                total_counter.update(file_counter)
                logger.debug(f"Completed processing {file_path.name}")
            except Exception as e:
                logger.error(f"Error processing {file_path}: {e}")
    return total_counter


def save_results_json(counter: Counter, output_file: Path):
    sorted_words = dict(sorted(counter.items(), key=lambda x: (-x[1], x[0])))
    results = {
        "metadata": {
            "total_words": sum(counter.values()),
            "unique_words": len(counter),
            "timestamp": import_datetime().isoformat(),
        },
        "word_counts": sorted_words,
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"Results saved to {output_file}")


def import_datetime():
    from datetime import datetime

    return datetime.now()


def main():
    directory = Path.cwd()
    output_file = Path("counter.json")
    max_workers = None
    logger.info(f"Starting word frequency analysis in {directory}")
    text_files = collect_text_files(directory)
    if not text_files:
        logger.warning("No text files found in the current directory!")
        save_results_json(Counter(), output_file)
        return
    logger.info(f"Processing {len(text_files)} files using parallel processing...")
    total_counter = process_files_parallel(text_files, max_workers)
    unique_words = len(total_counter)
    total_words = sum(total_counter.values())
    save_results_json(total_counter, output_file)
    logger.info("Analysis complete!")
    logger.info(f"Total words found: {total_words}")
    logger.info(f"Unique words found: {unique_words}")
    print("\n" + "=" * 40)
    print("Top 10 Most Common Words:")
    print("-" * 40)
    for word, count in total_counter.most_common(10):
        print(f"{word:<20} {count:>8}")
    print("-" * 40)
    print(f"\nFull results saved to: {output_file.absolute()}")


if __name__ == "__main__":
    raise SystemExit(main())
