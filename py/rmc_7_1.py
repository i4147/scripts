#!/data/data/com.termux/files/usr/bin/python
from __future__ import annotations

import argparse
import multiprocessing as mp
import shutil
import sys
from pathlib import Path

from dh import ASTStripper, CSTStripper, StripFileResult, TSStripper, get_pyfiles

_BACKENDS: tuple[type, ...] = (CSTStripper, TSStripper, ASTStripper)
_OPTS: dict[str, bool] = {}


def _init(opts: dict[str, bool]) -> None:
    global _OPTS
    _OPTS = opts


def _strip_one(task: tuple[int, str]) -> tuple[int, str, StripFileResult]:
    idx, path = task
    last_err = "all backends failed"
    for cls in _BACKENDS:
        try:
            stripper = cls(**_OPTS)
        except ImportError:
            continue
        try:
            result = stripper.strip_file(path)
        except Exception as exc:
            last_err = f"{cls.__name__}: {exc}"
            continue
        if result.valid:
            return idx, path, result
        last_err = result.error or last_err
    return idx, path, StripFileResult(path=Path(path), modified=False, valid=False, error=last_err)


def _bytes_str(result: StripFileResult) -> str:
    return str(result.bytes_reduced) if result.valid else "ERR"


def _print_results(results: list[tuple[int, str, StripFileResult]]) -> None:
    results.sort(key=lambda item: item[0])
    term_w = shutil.get_terminal_size(fallback=(80, 24)).columns
    num_w = len(str(results[-1][0]))
    idx_w = num_w + 2
    bytes_w = max(len(_bytes_str(r[2])) for r in results)
    max_fname = max(len(Path(r[1]).name) for r in results)
    available = term_w - idx_w - 1 - 2 - bytes_w
    fname_w = max(8, min(max_fname, available))

    for idx, path, result in results:
        fname = Path(path).name
        if len(fname) > fname_w:
            fname = fname[: fname_w - 1] + "…"
        prefix = f"[{idx:>{num_w}}]"
        print(f"{prefix} {fname:<{fname_w}}  {_bytes_str(result):>{bytes_w}}")

    for idx, path, result in results:
        if not result.valid:
            print(f"[{idx}] {path}: {result.error}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dh-strip",
        description="Strip comments and/or docstrings from Python files recursively.",
    )
    parser.add_argument(
        "-c",
        "--strip-comments",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Strip comments (use --no-strip-comments to preserve)",
    )
    parser.add_argument(
        "-d",
        "--strip-docstrings",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Strip docstrings (use --no-strip-docstrings to preserve)",
    )
    parser.add_argument("--preserve-shebangs", action="store_true", help="Keep shebang lines")
    parser.add_argument(
        "--preserve-module-docstring",
        action="store_true",
        help="Keep module-level docstrings",
    )
    parser.add_argument(
        "--preserve-directives",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep # type:, # noqa:, etc.",
    )
    parser.add_argument(
        "--validate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Validate the output by re-parsing",
    )
    parser.add_argument(
        "--preserve-commented-code",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep commented-out code blocks",
    )
    args = parser.parse_args()

    opts: dict[str, bool] = {
        "strip_comments": args.strip_comments,
        "strip_docstrings": args.strip_docstrings,
        "preserve_shebangs": args.preserve_shebangs,
        "preserve_module_docstring": args.preserve_module_docstring,
        "preserve_directives": args.preserve_directives,
        "validate": args.validate,
        "preserve_commented_code": args.preserve_commented_code,
    }

    files = sorted(get_pyfiles(Path(".")))
    if not files:
        print("No Python files found.", file=sys.stderr)
        return

    tasks: list[tuple[int, str]] = [(i, str(p)) for i, p in enumerate(files, 1)]
    results: list[tuple[int, str, StripFileResult]] = []
    with mp.Pool(8, initializer=_init, initargs=(opts,)) as pool:
        for result in pool.imap_unordered(_strip_one, tasks):
            results.append(result)

    _print_results(results)


if __name__ == "__main__":
    main()
