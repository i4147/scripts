import re
import sys
from pathlib import Path

ITEM_START_RE = re.compile(
    '\n    ^\\s*\n    (?:pub(?:\\([^)]*\\))?\\s+)*\n    (?:async\\s+)?(?:const\\s+)?(?:unsafe\\s+)?\n    (?:extern\\s+"[^"]+"\\s+)?\n    (fn|impl|trait|mod|enum|struct|union)\\b\n    ',
    re.VERBOSE,
)


def remove_comments(src: str) -> str:
    out = []
    i = 0
    n = len(src)
    in_str = False
    in_char = False
    in_line_comment = False
    in_block_comment = 0
    escape = False
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if not in_str and (not in_char) and (in_block_comment == 0) and (ch == "/") and (nxt == "/"):
            i += 2
            while i < n and src[i] != "\n":
                i += 1
            continue
        if not in_str and (not in_char) and (in_block_comment == 0) and (ch == "/") and (nxt == "*"):
            in_block_comment = 1
            i += 2
            continue
        if in_block_comment > 0:
            if ch == "/" and nxt == "*":
                in_block_comment += 1
                i += 2
                continue
            if ch == "*" and nxt == "/":
                in_block_comment -= 1
                i += 2
                continue
            i += 1
            continue
        if in_str:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if in_char:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                in_char = False
            i += 1
            continue
        if ch == '"':
            out.append(ch)
            in_str = True
            i += 1
            continue
        if ch == "'":
            out.append(ch)
            in_char = True
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def find_matching_brace(src: str, open_pos: int) -> int:
    n = len(src)
    i = open_pos + 1
    depth = 1
    in_str = False
    in_char = False
    in_line_comment = False
    in_block_comment = 0
    escape = False
    while i < n and depth > 0:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment > 0:
            if ch == "/" and nxt == "*":
                in_block_comment += 1
                i += 2
                continue
            if ch == "*" and nxt == "/":
                in_block_comment -= 1
                i += 2
                continue
            i += 1
            continue
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if in_char:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                in_char = False
            i += 1
            continue
        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = 1
            i += 2
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if ch == "'":
            in_char = True
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return i


def compress_rust_items(src: str) -> str:
    lines = src.splitlines(keepends=True)
    out = []
    i = 0
    n = len(lines)
    pending_attrs = []
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("#[") or stripped.startswith("#!["):
            pending_attrs.append(line)
            i += 1
            continue
        if ITEM_START_RE.match(line):
            out.extend(pending_attrs)
            pending_attrs.clear()
            text = "".join(lines[i:])
            brace_pos = text.find("{")
            if brace_pos != -1:
                before = text[: brace_pos + 1]
                body_start_global = sum((len(x) for x in lines[:i])) + brace_pos
                body_end_global = find_matching_brace(src, body_start_global)
                out.append(before)
                out.append("...}")
                consumed = body_end_global
                prefix_len = sum((len(x) for x in lines[:i]))
                remaining = consumed - prefix_len
                j = i
                acc = 0
                while j < n and acc + len(lines[j]) <= remaining:
                    acc += len(lines[j])
                    j += 1
                i = j
                continue
        if pending_attrs:
            out.extend(pending_attrs)
            pending_attrs.clear()
        out.append(line)
        i += 1
    if pending_attrs:
        out.extend(pending_attrs)
    return "".join(out)


def cleanup_whitespace(src: str) -> str:
    lines = []
    blank = False
    for line in src.splitlines():
        line = line.rstrip()
        if not line.strip():
            if not blank:
                lines.append("")
            blank = True
        else:
            lines.append(line)
            blank = False
    return "\n".join(lines) + ("\n" if src.endswith("\n") else "")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python compress_rust.py path/to/file.rs", file=sys.stderr)
        sys.exit(1)
    in_path = Path(sys.argv[1])
    if not in_path.is_file():
        print(f"Error: file not found: {in_path}", file=sys.stderr)
        sys.exit(1)
    src = in_path.read_text(encoding="utf-8")
    src = remove_comments(src)
    src = compress_rust_items(src)
    src = cleanup_whitespace(src)
    out_path = in_path.with_name(in_path.stem + "_compressed" + in_path.suffix)
    out_path.write_text(src, encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
