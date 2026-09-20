import argparse
import re
import sys
from collections.abc import Iterable, Iterator
from multiprocessing import Pool
from pathlib import Path
from typing import Optional, Set, Tuple
from loguru import logger
COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
DEFAULT_EXTENSIONS = (".html", ".htm", ".css")
POOL_SIZE = 8
FileResult = tuple[Path, bool, str | None]
def remove_comments_from_file(file_path):
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        new_content = COMMENT_PATTERN.sub("", content)
        if new_content != content:
            file_path.write_text(new_content, encoding="utf-8", errors="ignore")
            return (file_path, True, None)
        return (file_path, False, None)
    except Exception as exc:  
        return (file_path, False, str(exc))
def find_files(directory, extensions):
    if not directory.exists():
        raise ValueError(f"Directory {directory} does not exist")
    for file_path in directory.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in extensions:
            yield file_path
def _normalize_extension(ext):
    ext = ext.lower()
    return ext if ext.startswith(".") else f".{ext}"
def _build_parser():
    parser = argparse.ArgumentParser(
        description="Remove HTML comments from HTML and CSS files recursively."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to process (default: current directory)",
    )
    parser.add_argument(
        "-e",
        "--extensions",
        nargs="+",
        default=list(DEFAULT_EXTENSIONS),
        help="File extensions to process (default: .html .htm .css)",
    )
    return parser
def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    extensions = {_normalize_extension(ext) for ext in args.extensions}
    directory = Path(args.directory)
    try:
        files = list(find_files(directory, extensions))
    except ValueError as exc:
        logger.error("{}", exc)
        return 1
    if not files:
        logger.info("No files found with extensions: {}", ", ".join(extensions))
        return 0
    logger.info("Found {} files to process", len(files))
    logger.info("Using {} workers", POOL_SIZE)
    logger.info("{}", "-" * 40)
    updated_count = 0
    error_count = 0
    try:
        with Pool(processes=POOL_SIZE) as pool:
            async_results = [
                (file_path, pool.apply_async(remove_comments_from_file, (file_path,)))
                for file_path in files
            ]
            for file_path, async_result in async_results:
                _, was_updated, error = async_result.get()
                try:
                    rel_path = file_path.relative_to(directory)
                except ValueError:
                    rel_path = file_path
                if error:
                    logger.error("ERROR: {} - {}", rel_path, error)
                    error_count += 1
                elif was_updated:
                    logger.info("UPDATED: {}", rel_path)
                    updated_count += 1
    except Exception as exc:  
        logger.exception("Fatal error: {}", exc)
        return 1
    logger.info("{}", "-" * 40)
    logger.info("Summary:")
    logger.info("  Total files processed: {}", len(files))
    logger.info("  Files updated: {}", updated_count)
    logger.info("  Errors: {}", error_count)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
