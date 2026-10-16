#!/data/data/com.termux/files/usr/bin/python3.12

from __future__ import annotations
import argparse
import ast
import shutil
import sys
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Sequence

from loguru import logger

from dh import get_pyfiles


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Python files for syntax errors and move invalid ones into per-directory 'error' folders."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path.cwd()],
        help="File or directory paths to process (default: current working directory).",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Report intended actions without modifying the filesystem.",
    )
    parser.add_argument(
        "--pool-method",
        choices=["map", "imap_unordered", "starmap", "apply_async"],
        default="starmap",
        help="Multiprocessing Pool method to use (default: starmap).",
    )
    return parser.parse_args(argv)


def unique_destination(dest_dir: Path, filename: str) -> Path:
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        candidate = dest_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def check_and_quarantine(path: Path, dry_run: bool) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
        return False
    except Exception as exc:
        logger.warning("Syntax error in {}: {}", path, exc)
        error_dir = path.parent / "error"
        dest = unique_destination(error_dir, path.name)
        if dry_run:
            logger.info("[dry-run] Would copy {} -> {}", path, dest)
        else:
            error_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            logger.info("copied {} -> {}", path, dest)
        return True


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    paths: list[Path] = [p.resolve() for p in args.paths]
    py_files: list[Path] = get_pyfiles(*paths)
    if not py_files:
        logger.info("No Python files found.")
        return 0
    logger.info(
        "Processing {} file(s) with 8 workers (dry-run={}, pool-method={})",
        len(py_files),
        args.dry_run,
        args.pool_method,
    )
    invalid_count = 0
    with Pool(processes=8) as pool:
        if args.pool_method == "map":
            worker = partial(check_and_quarantine, dry_run=args.dry_run)
            results: list[bool] = pool.map(worker, py_files)
            invalid_count = sum(results)
        elif args.pool_method == "imap_unordered":
            worker = partial(check_and_quarantine, dry_run=args.dry_run)
            results_iter = pool.imap_unordered(worker, py_files)
            invalid_count = sum(results_iter)
        elif args.pool_method == "starmap":
            args_list: list[tuple[Path, bool]] = [(p, args.dry_run) for p in py_files]
            results = pool.starmap(check_and_quarantine, args_list)
            invalid_count = sum(results)
        else:
            async_results = [pool.apply_async(check_and_quarantine, (path, args.dry_run)) for path in py_files]
            for result in async_results:
                if result.get():
                    invalid_count += 1
    logger.info("Finished. {} file(s) had syntax errors.", invalid_count)
    return invalid_count


if __name__ == "__main__":
    sys.exit(main())
