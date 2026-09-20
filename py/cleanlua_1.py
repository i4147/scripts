Refactor this Python script with the following changes:
1. Bug fixes: Fix any issues that would cause error
2. Type annotations: Add complete type hints to all functions, methods, class attributes, arguments, return types, module-level constants, and variables where missing. Ensure the code passes a strict type checker (e.g., mypy/pyright).
3. Docstrings:
   · If missing, add a module docstring as the first lines after the shebang. This docstring must be written as a concise prompt that could regenerate the entire script.
   · Add missing docstrings to all functions and classes.
4. Logging: Replace print statements and the standard logging module with loguru.
5. Path handling: Replace all os.path usage with pathlib.if exists
Return the fully refactored script.

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import tree_sitter_lua
from tree_sitter import Language, Parser

LUA_LANGUAGE = Language(tree_sitter_lua.language())
LUA_EXTS = {".lua"}
_PARSER: Parser | None = None


def get_parser() -> Parser:
    global _PARSER
    if _PARSER is None:
        _PARSER = Parser(LUA_LANGUAGE)
    return _PARSER


def collect_comment_ranges(root) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "comment":
            ranges.append((node.start_byte, node.end_byte))
            continue
        for child in reversed(node.children):
            stack.append(child)
    return ranges


def strip_comments(content: bytes) -> tuple[bytes, int]:
    tree = get_parser().parse(content)
    ranges = collect_comment_ranges(tree.root_node)
    if not ranges:
        return content, 0
    ranges.sort(key=lambda r: r[0])
    out = bytearray()
    last = 0
    for start, end in ranges:
        out.extend(content[last:start])
        last = end
    out.extend(content[last:])
    return bytes(out), len(ranges)


def process_file(path: Path, base: Path) -> tuple[str, int, str]:
    try:
        content = path.read_bytes()
        new_content, count = strip_comments(content)
        if new_content != content:
            path.write_bytes(new_content)
        try:
            rel = str(path.relative_to(base))
        except ValueError:
            rel = str(path)
        return rel, count, ""
    except Exception as exc:
        return str(path), 0, str(exc)


def iter_lua_files(paths: list[Path]):
    seen: set[Path] = set()
    for p in paths:
        if p.is_file() and p.suffix.lower() in LUA_EXTS:
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*.lua")):
                rp = f.resolve()
                if rp not in seen:
                    seen.add(rp)
                    yield f


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Remove comments from Lua files in place (tree-sitter powered)."
    )
    ap.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories. Defaults to current directory recursively.",
    )
    ap.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=max(1, (os.cpu_count() or 2)),
        help="Number of parallel workers (default: CPU count).",
    )
    args = ap.parse_args()
    inputs = list(args.paths) if args.paths else [Path(".")]
    files = list(iter_lua_files(inputs))
    if not files:
        print("No Lua files to process.", file=sys.stderr)
        return 1
    base = Path.cwd()
    total_comments = 0
    files_changed = 0
    errors = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(process_file, p, base): p for p in files}
        for fut in as_completed(futs):
            rel, count, err = fut.result()
            if err:
                errors += 1
                print(f"{rel}: ERROR: {err}", file=sys.stderr)
                continue
            total_comments += count
            if count > 0:
                files_changed += 1
            print(f"{rel}: {count} comment(s) removed")
    print(
        f"\nSummary: {files_changed}/{len(files)} file(s) changed, "
        f"{total_comments} comment(s) removed, {errors} error(s)."
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
