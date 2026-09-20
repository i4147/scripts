from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from dh import fsz
from tree_sitter import Language, Parser
from tree_sitter_lua import language as lua_language


def _build_parser() -> Parser:
    lang = Language(lua_language())
    parser = Parser()
    try:
        parser.language = lang
    except (AttributeError, TypeError):
        parser.set_language(lang)
    return parser


PARSER = _build_parser()


def _find_comment_ranges(tree) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "comment":
            ranges.append((node.start_byte, node.end_byte))
        else:
            stack.extend(node.children)
    return ranges


def remove_comments(source: bytes) -> tuple[bytes, int, int]:
    tree = PARSER.parse(source)
    ranges = _find_comment_ranges(tree)
    if not ranges:
        return source, 0, 0
    ranges.sort(key=lambda r: r[0], reverse=True)
    result = source
    bytes_removed = 0
    for start, end in ranges:
        line_start = start
        while line_start > 0 and result[line_start - 1 : line_start] not in (
            b"\n",
            b"\r",
        ):
            line_start -= 1
        leading = result[line_start:start]
        only_ws_before = leading.strip() == b""
        nl_len = 0
        if result[end : end + 2] == b"\r\n":
            nl_len = 2
        elif result[end : end + 1] in (b"\n", b"\r"):
            nl_len = 1
        if only_ws_before and nl_len:
            cut_start = line_start
            cut_end = end + nl_len
        else:
            cut_start = start
            cut_end = end
        result = result[:cut_start] + result[cut_end:]
        bytes_removed += cut_end - cut_start
    return result, len(ranges), bytes_removed


def process_file(path: Path, base: Path) -> dict:
    try:
        original = path.read_bytes()
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
            print(f"warning: {item} does not exist, skipping", file=sys.stderr)
            continue
        if item.is_file():
            if item.suffix == ".lua":
                files.append((item, item.parent))
            else:
                print(f"warning: {item} is not a .lua file, skipping", file=sys.stderr)
        elif item.is_dir():
            base = item
            files.extend((p, base) for p in sorted(base.rglob("*.lua")))
        else:
            print(
                f"warning: {item} is neither a file nor directory, skipping",
                file=sys.stderr,
            )
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove comments from Lua files using tree-sitter.")
    ap.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process (default: current directory).",
    )
    ap.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="Number of parallel workers (default: cpu_count).",
    )
    args = ap.parse_args()
    paths = args.paths or [Path.cwd()]
    files = collect_files(paths)
    if not files:
        print("No .lua files found.")
        return 0
    workers = args.jobs
    print(f"Processing {len(files)} Lua file(s) with {workers or 'all'} worker(s)...\n")
    t0 = time.monotonic()
    total_files = 0
    total_comments = 0
    total_removed = 0
    errors = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(process_file, p, base) for p, base in files]
        for fut in as_completed(futures):
            s = fut.result()
            total_files += 1
            rel = s["path"]
            if s["status"] == "error":
                errors += 1
                print(f"  ✗ {rel}  [ERROR] {s['error']}")
            elif s["status"] == "noop":
                print(f"  · {rel}  (no comments)")
            else:
                total_comments += s["comments"]
                total_removed += s["removed"]
                saved = s["before"] - s["after"]
                pct = (saved / s["before"] * 40) if s["before"] else 0.0
                print(f"  ✓ {rel}  {s['comments']} comment(s) removed · {fsz(saved)} (-{pct:.1f}%)")
    elapsed = time.monotonic() - t0
    print("\n" + "─" * 40)
    print(f"  Files processed  : {total_files}")
    print(f"  Comments removed : {total_comments}")
    print(f"  Bytes removed    : {fsz(total_removed)}")
    print(f"  Errors           : {errors}")
    print(f"  Elapsed          : {elapsed:.2f}s")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
