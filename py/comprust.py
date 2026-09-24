import sys
from pathlib import Path


def strip_comments_and_compress_rust(src: str) -> str:
    out = []
    i = 0
    n = len(src)
    in_str = False
    in_char = False
    in_line_comment = False
    in_block_comment = 0
    escape = False

    def skip_line_comment(pos: int) -> int:
        while pos < n and src[pos] != "\n":
            pos += 1
        return pos

    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if not in_str and (not in_char) and (in_block_comment == 0) and (ch == "/") and (nxt == "/"):
            i = skip_line_comment(i + 2)
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
        if ch == "{":
            depth = 1
            j = i + 1
            j_in_str = False
            j_in_char = False
            j_in_block_comment = 0
            j_escape = False
            while j < n and depth > 0:
                cj = src[j]
                nj = src[j + 1] if j + 1 < n else ""
                if j_in_block_comment > 0:
                    if cj == "/" and nj == "*":
                        j_in_block_comment += 1
                        j += 2
                        continue
                    if cj == "*" and nj == "/":
                        j_in_block_comment -= 1
                        j += 2
                        continue
                    j += 1
                    continue
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
                if cj == "/" and nj == "*":
                    j_in_block_comment = 1
                    j += 2
                    continue
                if cj == '"':
                    j_in_str = True
                    j += 1
                    continue
                if cj == "'":
                    j_in_char = True
                    j += 1
                    continue
                if cj == "{":
                    depth += 1
                elif cj == "}":
                    depth -= 1
                j += 1
            out.append("{...}")
            i = j
            continue
        out.append(ch)
        i += 1
    result = "".join(out)
    lines = []
    prev_blank = False
    for line in result.splitlines():
        line = line.rstrip()
        if not line.strip():
            if not prev_blank:
                lines.append("")
            prev_blank = True
        else:
            lines.append(line)
            prev_blank = False
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
    compressed = strip_comments_and_compress_rust(src)
    out_path = in_path.with_name(in_path.stem + "_compressed" + in_path.suffix)
    out_path.write_text(compressed, encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
