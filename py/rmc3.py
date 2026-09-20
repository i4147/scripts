import ast
import sys
from pathlib import Path

from dh import DOC_TH1, cprint, fsz, get_pyfiles, gsz, mpf3, read_lines

DOCTH1 = DOC_TH1 * 2


def process_file(fp) -> str:
    lines = read_lines(fp, ke=False)
    nl = []
    removed = 0
    for line in lines:
        stripped = line.lstrip().rstrip().strip()
        if stripped.startswith(DOC_TH1) and stripped.endswith(DOC_TH1) and (stripped != DOCTH1):
            print(line)
            removed += 1
            continue
        nl.append(line)
    if removed:
        try:
            code = "\n".join(nl)
            _ = ast.parse(code)
            fp.write_text(code, encoding="utf8")
            return f"{fp.name} : OK"
        except:
            return f"{fp.name} : AST PARSE ERROR"
    else:
        return f"{fp.name} : NOCHANGE"


def main() -> None:
    cwd = Path.cwd()
    before = gsz(cwd)
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
        files = get_pyfiles(cwd)
    results = mpf3(process_file, files)
    for result in results:
        if result:
            print(result)
    diffsize = before - gsz(cwd)
    cprint(f"space change : {fsz(diffsize)}", "cyan")


if __name__ == "__main__":
    sys.exit(main())
