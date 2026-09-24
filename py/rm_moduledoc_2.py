import ast
import re
from multiprocessing.pool import Pool
from pathlib import Path
from typing import Final
from loguru import logger

MAX_WORKERS = 8
SCAN_LIMIT = 5


def _build_pattern(file_name):
    return re.compile(rf'^\s*"""\s*Module for\s+{re.escape(file_name)}\s*\.?\s*"""\s*$')


def _validate_source(source):
    try:
        ast.parse(source)
    except SyntaxError as exc:
        logger.warning("AST validation failed: {}", exc)
        return False
    return True


def clean_single_file(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        logger.error("Error reading {}: {}", path.name, exc)
        return
    if not lines:
        print("Skipped empty file: {}", path.name)
        return
    pattern = _build_pattern(path.name)
    scan_limit = min(SCAN_LIMIT, len(lines))
    removed_index = None
    for i in range(scan_limit):
        if pattern.match(lines[i].strip()):
            lines.pop(i)
            removed_index = i
            break
    if removed_index is None:
        print(
            "No automated docstring in top {} lines of: {}",
            SCAN_LIMIT,
            path.name,
        )
        return
    new_source = "".join(lines)
    if not _validate_source(new_source):
        logger.error(
            "Refusing to write {}: modified source failed AST validation",
            path.name,
        )
        return
    try:
        path.write_text(new_source, encoding="utf-8")
    except OSError as exc:
        logger.error("Error writing {}: {}", path.name, exc)
        return
    logger.success("Cleaned docstring from line {} of: {}", removed_index + 1, path.name)


def main():
    current_dir = Path(".")
    self_name = Path(__file__).name
    py_files = [f for f in current_dir.glob("*.py") if f.name != self_name]
    if not py_files:
        logger.warning("No Python files found in the current directory.")
        return 0
    print(
        "Scanning the top {} lines of {} files with {} workers...",
        SCAN_LIMIT,
        len(py_files),
        MAX_WORKERS,
    )
    pool = Pool(processes=MAX_WORKERS)
    try:
        async_results = [pool.apply_async(clean_single_file, (py_file,)) for py_file in py_files]
        for async_result in async_results:
            async_result.get()
    finally:
        pool.close()
        pool.join()
    logger.success("Fast cleanup complete!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
