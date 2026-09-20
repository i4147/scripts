import ast
import sys
from pathlib import Path

from dh import DOC_TH1, DOC_TH2, fsz, get_pyfiles, gsz, mpf3


def preprocess(orig: str):
    cleaned = []
    lines = orig.splitlines(keepends=True)
    for line in lines[1:]:
        stripped = line.strip()
        if "#" in stripped and (not stripped.startswith("#")):
            indx = line.index("#")
            cleaned.append(line[:indx])
            continue
        if not stripped.startswith("#"):
            cleaned.append(line)
    code = "".join(cleaned)
    try:
        _ = ast.parse(code)
        return code
    except:
        return orig


def process_file(path: Path) -> bool:
    gsz(path)
    try:
        original = path.read_text(encoding="utf-8")
        if DOC_TH1 not in original and DOC_TH2 not in original and ("#!" not in original) and ("#" not in original):
            return True
        result = preprocess(original)
        path.write_text(result, encoding="utf-8")
    except:
        return None


def main() -> None:
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(f) for f in args] if args else get_pyfiles(cwd)
    numfiles = len(files)
    if numfiles == 1:
        process_file(files[0])
        sys.exit(0)
    mpf3(process_file, files)
    diff_size = before - gsz(cwd)
    print(f"space saved : {fsz(diff_size)}")


if __name__ == "__main__":
    main()
