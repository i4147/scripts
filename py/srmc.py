import ast
import sys
from pathlib import Path

from dh import fsz, get_files, gsz, mpf


def _get_comments_symbol(text: str, symbol: str) -> list[str]:
    comments: list = []
    i: int = 0
    indexes: list = []
    for i in range(len(text)):
        if text[i] == symbol and len(text) > i + 2 and (text[i] == text[i + 1] == text[i + 2]):
            if len(indexes) == 0:
                indexes.append(i)
            elif len(indexes) == 1:
                indexes.append(i + 2)
                comments.append(text[indexes[0] : indexes[1] + 1])
                indexes = []
    return comments


def _get_comments_simplequot(text: str) -> list[str]:
    return _get_comments_symbol(text=text, symbol="'")


def _get_comments_doublequot(text: str) -> list[str]:
    return _get_comments_symbol(text=text, symbol='"')


def remove_comments(text: str) -> str:
    comments = _get_comments_simplequot(text=text)
    for comment in comments:
        text = text.replace(comment, "")
    comments = _get_comments_doublequot(text=text)
    for comment in comments:
        text = text.replace(comment, "")
    lines = text.split("\n")
    new_lines = []
    for line in lines:
        if "#" in line:
            line_without_comment = "#".join(line.split("#")[:1]).rstrip(" ")
            new_lines.append(line_without_comment)
        else:
            new_lines.append(line)
    return "\n".join(new_lines)


def process_file(fp: Path) -> None:
    data = fp.read_text(encoding="utf-8")
    result = remove_comments(data)
    try:
        _ = ast.parse(result)
        fp.write_text(result, encoding="utf-8")
    except:
        print("result code is not valid")
        backup_path = fp.with_suffix(fp.suffix + ".bak")
        backup_path.write_text(data, encoding="utf-8")
        fp.write_text(result, encoding="utf-8")
        print(f"backup created {backup_path.name}")


def main() -> None:
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(f) for f in args] if args else get_files(cwd, ext=[".py"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    mpf(process_file, files)
    diff_size = before - gsz(cwd)
    print(f"space saved : {fsz(diff_size)}")


if __name__ == "__main__":
    main()
