#!/data/data/com.termux/files/usr/bin/python
from __future__ import annotations
import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from multiprocessing import Pool
from pathlib import Path
from typing import TYPE_CHECKING, Final
from loguru import logger

if TYPE_CHECKING:
    from multiprocessing.pool import AsyncResult
WORKER_COUNT: Final[int] = 8
DEFAULT_TIMEOUT: Final[float] = 30.0
FILE_PATTERN: Final[str] = "*.py"


class Outcome(str, Enum):
    SUCCESS = "success"
    MODULE_NOT_FOUND = "ModuleNotFoundError"
    IMPORT_ERROR = "ImportError"
    SYNTAX_ERROR = "SyntaxError"
    ATTRIBUTE_ERROR = "AttributeError"
    TYPE_ERROR = "TypeError"
    VALUE_ERROR = "ValueError"
    KEYBOARD_INTERRUPT = "KeyboardInterrupt"
    TIMEOUT = "TimeoutError"
    OTHER_ERROR = "OtherError"


@dataclass(slots=True)
class FileResult:
    path: Path
    outcome: Outcome
    returncode: int | None = None
    stderr: str = ""
    duration: float = 0.0


@dataclass(slots=True)
class Summary:
    results: list[FileResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.results if r.outcome is Outcome.SUCCESS)

    @property
    def failed(self) -> int:
        return self.total - self.succeeded

    def counts_by_outcome(self) -> dict[Outcome, int]:
        counts: dict[Outcome, int] = {}
        for result in self.results:
            counts[result.outcome] = counts.get(result.outcome, 0) + 1
        return counts


def discover_python_files(directory: Path, recursive: bool) -> list[Path]:
    if recursive:
        return sorted(p for p in directory.rglob(FILE_PATTERN) if p.is_file())
    return sorted(p for p in directory.glob(FILE_PATTERN) if p.is_file())


def _classify_failure(stderr: str, returncode: int) -> Outcome:
    checks: tuple[tuple[str, Outcome], ...] = (
        ("ModuleNotFoundError", Outcome.MODULE_NOT_FOUND),
        ("ImportError", Outcome.IMPORT_ERROR),
        ("SyntaxError", Outcome.SYNTAX_ERROR),
        ("AttributeError", Outcome.ATTRIBUTE_ERROR),
        ("TypeError", Outcome.TYPE_ERROR),
        ("ValueError", Outcome.VALUE_ERROR),
    )
    for needle, outcome in checks:
        if needle in stderr:
            return outcome
    if "KeyboardInterrupt" in stderr or returncode in (-2, 130):
        return Outcome.KEYBOARD_INTERRUPT
    return Outcome.OTHER_ERROR


def run_file(path: Path, timeout: float) -> FileResult:
    import time

    start = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return FileResult(
            path=path,
            outcome=Outcome.TIMEOUT,
            duration=time.monotonic() - start,
        )
    except KeyboardInterrupt:
        return FileResult(
            path=path,
            outcome=Outcome.KEYBOARD_INTERRUPT,
            duration=time.monotonic() - start,
        )
    duration = time.monotonic() - start
    if completed.returncode == 0:
        return FileResult(
            path=path,
            outcome=Outcome.SUCCESS,
            returncode=0,
            duration=duration,
        )
    outcome = _classify_failure(completed.stderr, completed.returncode)
    return FileResult(
        path=path,
        outcome=outcome,
        returncode=completed.returncode,
        stderr=completed.stderr.strip(),
        duration=duration,
    )


def _log_result(result: FileResult, verbose: bool) -> None:
    if result.outcome is Outcome.SUCCESS:
        if verbose:
            logger.success(f"OK   {result.path} ({result.duration:.2f}s)")
    else:
        logger.error(f"FAIL {result.path} -> {result.outcome.value} (rc={result.returncode}, {result.duration:.2f}s)")
        if verbose and result.stderr:
            logger.debug(f"{result.path} stderr:\n{result.stderr}")


def report_summary(summary: Summary) -> None:
    print("=" * 60)
    print(f"Summary: {summary.total} file(s), {summary.succeeded} succeeded, {summary.failed} failed")
    counts = summary.counts_by_outcome()
    for outcome in Outcome:
        count = counts.get(outcome)
        if count:
            print(f"  {outcome.value:<22} {count}")
    print("=" * 60)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyrunner",
        description=("Recursively find and execute all .py files in a directory with a per-file timeout, in parallel."),
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Directory to search for Python files.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not descend into subdirectories.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Per-file timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable verbose logging (default: enabled).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    directory: Path = args.directory
    recursive: bool = not args.no_recursive
    timeout: float = args.timeout
    verbose: bool = args.verbose
    if not directory.is_dir():
        logger.error(f"Not a directory: {directory}")
        return 2
    files = discover_python_files(directory, recursive)
    if not files:
        logger.warning(f"No Python files found in {directory}")
        return 0
    print(
        f"Found {len(files)} Python file(s) in {directory} "
        f"(recursive={recursive}, timeout={timeout}s, workers={WORKER_COUNT})"
    )
    summary = Summary()
    try:
        with Pool(processes=WORKER_COUNT) as pool:
            pending: list[tuple[Path, AsyncResult[FileResult]]] = [
                (path, pool.apply_async(run_file, (path, timeout))) for path in files
            ]
            for path, async_result in pending:
                try:
                    result = async_result.get(timeout=timeout + 5.0)
                except Exception as exc:
                    result = FileResult(
                        path=path,
                        outcome=Outcome.OTHER_ERROR,
                        stderr=str(exc),
                    )
                summary.results.append(result)
                _log_result(result, verbose)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user; shutting down workers.")
        return 130
    report_summary(summary)
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
