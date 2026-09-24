from __future__ import annotations

import argparse
import time
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from dh import fsz
from loguru import logger
from tree_sitter import Language, Node, Parser, Tree
from tree_sitter_lua import language as lua_language

WORKERS: int = 8


def _build_parser() -> Parser:
    lang: Language = Language(lua_language())
    parser: Parser = Parser()
    try:
        parser.language = lang
    except (AttributeError, TypeError):
        parser.set_language(lang)
    return parser


PARSER: Parser = _build_parser()


def _find_comment_ranges(tree: Tree) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    stack: list[Node] = [tree.root_node]
    while stack:
        node: Node = stack.pop()
        if node.type == "comment":
            ranges.append((node.start_byte, node.end_byte))
        else:
            stack.extend(node.children)
    return ranges


def remove_comments(source: bytes) -> tuple[bytes, int, int]:
    tree: Tree = PARSER.parse(source)
    ranges: list[tuple[int, int]] = _find_comment_ranges(tree)
    if not ranges:
        return source, 0, 0
    ranges.sort(key=lambda r: r[0], reverse=True)
    result: bytes = source
    bytes_removed: int = 0
    for start, end in ranges:
        line_start: int = start
        while line_start > 0 and result[line_start - 1 : line_start] not in (
            b"\n",
            b"\r",
        ):
            line_start -= 1
        leading: bytes = result[line_start:start]
        only_ws_before: bool = leading.strip() == b""
        nl_len: int = 0
        if result[end : end + 2] == b"\r\n":
            nl_len = 2
        elif result[end : end + 1] in (b"\n", b"\r"):
            nl_len = 1
        cut_start: int
        cut_end: int
        if only_ws_before and nl_len:
            cut_start = line_start
            cut_end = end + nl_len
        else:
            cut_start = start
            cut_end = end
        result = result[:cut_start] + result[cut_end:]
        bytes_removed += cut_end - cut_start
    return result, len(ranges), bytes_removed


def process_file(path: Path, base: Path) -> dict[str, Any]:
    try:
        original: bytes = path.read_bytes()
        result: bytes
        n_comments: int
        bytes_removed: int
        result, n_comments, bytes_removed = remove_comments(original)
        if n_comments == 0:
            return {
                "path": path.relative_to(base),
                "status": "noop",
                "comments": 0,
                "removed": 0,
                "before": len(original),
                "after": len(original),
                "error": None,
            }
        path.write_bytes(result)
        return {
            "path": path.relative_to(base),
            "status": "ok",
            "comments": n_comments,
            "removed": bytes_removed,
            "before": len(original),
            "after": len(result),
            "error": None,
        }
    except Exception as exc:
        rel: Path
        try:
            rel = path.relative_to(base)
        except ValueError:
            rel = path
        return {
            "path": rel,
            "status": "error",
            "comments": 0,
            "removed": 0,
            "before": 0,
            "after": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }


def collect_files(paths: list[Path]) -> list[tuple[Path, Path]]:
    files: list[tuple[Path, Path]] = []
    for item in paths:
        if not item.exists():
            logger.warning("{} does not exist, skipping", item)
            continue
        if item.is_file():
            if item.suffix == ".lua":
                files.append((item, item.parent))
            else:
                logger.warning("{} is not a .lua file, skipping", item)
        elif item.is_dir():
            base: Path = item
            files.extend((p, base) for p in sorted(base.rglob("*.lua")))
        else:
            logger.warning("{} is neither a file nor directory, skipping", item)
    return files


def main() -> int:
    ap: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Remove comments from Lua files using tree-sitter."
    )
    ap.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process (default: current directory).",
    )
    args: argparse.Namespace = ap.parse_args()
    paths: list[Path] = args.paths or [Path.cwd()]
    files: list[tuple[Path, Path]] = collect_files(paths)
    if not files:
        logger.info("No .lua files found.")
        return 0
    logger.info("Processing {} Lua file(s) with {} worker(s)...\n", len(files), WORKERS)
    t0: float = time.monotonic()
    total_files: int = 0
    total_comments: int = 0
    total_removed: int = 0
    errors: int = 0
    with Pool(processes=WORKERS) as pool:
        async_results: list[Any] = [pool.apply_async(process_file, (p, base)) for p, base in files]
        for ar in async_results:
            s: dict[str, Any] = ar.get()
            total_files += 1
            rel: Path = s["path"]
            if s["status"] == "error":
                errors += 1
                logger.error("  ✗ {}  [ERROR] {}", rel, s["error"])
            elif s["status"] == "noop":
                logger.info("  · {}  (no comments)", rel)
            else:
                total_comments += s["comments"]
                total_removed += s["removed"]
                saved: int = s["before"] - s["after"]
                pct: float = (saved / s["before"] * 40) if s["before"] else 0.0
                logger.info(
                    "  ✓ {}  {} comment(s) removed · {} (-{:.1f}%)",
                    rel,
                    s["comments"],
                    fsz(saved),
                    pct,
                )
    elapsed: float = time.monotonic() - t0
    logger.info("\n{}", "─" * 40)
    logger.info("  Files processed  : {}", total_files)
    logger.info("  Comments removed : {}", total_comments)
    logger.info("  Bytes removed    : {}", fsz(total_removed))
    logger.info("  Errors           : {}", errors)
    logger.info("  Elapsed          : {:.2f}s", elapsed)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
