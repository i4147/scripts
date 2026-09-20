import ast
import re
import sys
from pathlib import Path

from dh import cprint, fsz, get_pyfiles, get_removed_lines, gsz, mpf3

SPECIAL_COMMENT_RE = re.compile("#\\s*(type:|fmt:|pylint|mypy)", re.IGNORECASE)
cwd = Path.cwd()


def strip_comments(source: str) -> str:
    lines = source.splitlines(keepends=False)
    cleaned_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#!"):
            cleaned_lines.append(line)
            continue
        if stripped.startswith("#") and SPECIAL_COMMENT_RE.search(stripped):
            cleaned_lines.append(line)
            continue
        if stripped.startswith("#"):
            continue
        new_line = ""
        in_single = in_double = False
        j = 0
        while j < len(line):
            char = line[j]
            if char == "'" and (not in_double):
                in_single = not in_single
            elif char == '"' and (not in_single):
                in_double = not in_double
            if not in_single and (not in_double) and (char == "#"):
                comment_text = line[j:]
                if SPECIAL_COMMENT_RE.search(comment_text):
                    new_line += comment_text
                break
            new_line += char
            j += 1
        cleaned_lines.append(new_line.rstrip())
    return "\n".join(cleaned_lines).rstrip() + "\n"


def process_file(path: Path) -> None:
    before = gsz(path)
    if not before:
        return
    try:
        original = path.read_text(encoding="utf-8")
        if not "#" in original:
            return
        final_code = strip_comments(original)
        try:
            _ = ast.parse(final_code)
            path.write_text(final_code, encoding="utf-8")
            after = gsz(path)
            print(f"✅ {path.name}", end=" | ")
            dsz = before - after
            if not dsz:
                cprint("(no change)", "grey")
                return
            ratio = dsz / before * 100
            cprint(f"{fsz(dsz)} | {ratio:.1f}%", "cyan")
            removed, _ = get_removed_lines(original, final_code)
            for k in removed:
                cprint(f"- {k}", "red")
            return
        except SyntaxError:
            cprint(f"{path.name} | ast parse error", "yellow")
            return
    except Exception as e:
        print(f"❌ {path}: {e}")


def main() -> None:
    args = sys.argv[1:]
    files = [Path(p.strip()) for p in args] if args else get_pyfiles(cwd)
    if not files:
        print("No Python files found.")
        return
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    mpf3(process_file, files)


if __name__ == "__main__":
    main()
