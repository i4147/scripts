import sys
from pathlib import Path

from autoflake import fix_code
from dh import cprint, get_pyfiles, get_removed_lines


def process_file(fp: Path) -> None:
    code = fp.read_text(encoding="utf-8")
    result = fix_code(code, remove_all_unused_imports=True)
    diff_size = len(code) - len(result)
    if diff_size:
        removed, added = get_removed_lines(code, result)
        cprint(f"changed lines of {fp.name} : ", "cyan")
        for k in removed:
            cprint(f" - {k}", "red")
        for x in removed:
            cprint(f" + {x}", "green")
        fp.write_text(result, encoding="utf-8")
    else:
        print(f"{fp.name} no change")


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_pyfiles(cwd)
    for f in files:
        process_file(f)
