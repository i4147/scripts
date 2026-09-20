
import sys
from pathlib import Path


def strip_comments(src: str) -> str:
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


def compress_top_level_blocks(src: str) -> str:
    out = []
    i = 0
    n = len(src)
    depth = 0
    in_str = False
    in_char = False
    in_line_comment = False
    in_block_comment = 0
    escape = False

    def is_item_start(text: str, pos: int) -> bool:
        head = text[max(0, pos - 200) : pos]
        keywords = ["fn", "impl", "trait", "enum", "struct", "mod"]
        return any((k in head for k in keywords))

    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
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
        if ch == "{":
            if is_item_start(src, i):
                j = i + 1
                d = 1
                j_in_str = False
                j_in_char = False
                j_escape = False
                while j < n and d > 0:
                    cj = src[j]
                    if j_in_str:
                        if j_escape:
                            j_escape = False
                        elif cj == "\\":
                            j_escape = True
                        elif cj == '"':
                            j_in_str = False
                        j += 1
                        continue
                    if j_in_char:
                        if j_escape:
                            j_escape = False
                        elif cj == "\\":
                            j_escape = True
                        elif cj == "'":
                            j_in_char = False
                        j += 1
                        continue
                    if cj == '"':
                        j_in_str = True
                    elif cj == "'":
                        j_in_char = True
                    elif cj == "{":
                        d += 1
                    elif cj == "}":
                        d -= 1
                    j += 1
                out.append("{...}")
                i = j
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def cleanup_whitespace(src: str) -> str:
    lines = []
    blank = False
    for line in src.splitlines():
        line = line.rstrip()
        if line.strip() == "":
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
    src = strip_comments(src)
    src = compress_top_level_blocks(src)
    src = cleanup_whitespace(src)
    out_path = in_path.with_name(in_path.stem + "_compressed" + in_path.suffix)
    out_path.write_text(src, encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
