import sys
from pathlib import Path


class Result:
    def __init__(self, text: str, comments_found: int, comments_removed_chars: int) -> None:
        self.text = text
        self.comments = comments_found
        self.removed = comments_removed_chars


def strip_comments(src: str, allow_semicolon: bool = True) -> Result:
    comments = 0
    removed = 0
    out_lines = []
    for line in src.splitlines(True):
        i, n = (0, len(line))
        IN_SGL, IN_DBL = (1, 2)
        state = 0
        cut = None
        while i < n:
            ch = line[i]
            if state == IN_SGL:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == "'":
                    state = 0
                i += 1
                continue
            if state == IN_DBL:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == '"':
                    state = 0
                i += 1
                continue
            if ch == "'":
                state = IN_SGL
                i += 1
                continue
            if ch == '"':
                state = IN_DBL
                i += 1
                continue
            if ch == "#":
                cut = i
                break
            if allow_semicolon and ch == ";":
                cut = i
                break
            i += 1
        if cut is not None:
            comments += 1
            removed += len(line) - cut
            out_lines.append(line[:cut].rstrip() + ("\n" if line.endswith("\n") else ""))
        else:
            out_lines.append(line)
    return Result("".join(out_lines), comments, removed)


def process_file(path: str | Path) -> None:
    path = Path(path)
    code = path.read_text(encoding="utf-8")
    result = strip_comments(code)

    if result.comments:
        path.write_text(result.text, encoding="utf-8")
        print(f"{path.name} : {result.comments}\n\n{result.removed}")
    else:
        print(f"{path.name} : (no change)")
    return


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []

    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(cwd)

    mpf3(process_file, files)


if __name__ == "__main__":
    sys.exit(main())
