import compileall
import sys
from pathlib import Path
from dh import get_pyfiles, mpf3

REMOVE_ORIG = False


def process_file(path) -> bool | None:
    path = Path(path)
    if not path.exists():
        return False
    if ".git" in path.parts:
        return None
    if path.is_dir():
        for f in path.rglob("*.py"):
            process_file(f)
    if path.is_file() and not path.is_symlink():
        pyc_file = path.with_suffix(".pyc")
        if pyc_file.exists():
            pyc_file.unlink()
        compileall.compile_file(path, optimize=0)
        if REMOVE_ORIG:
            path.unlink()
        return True
    return False


def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_pyfiles(p))
    else:
        files = get_pyfiles(cwd)
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    mpf3(process_file, files)


if __name__ == "__main__":
    sys.exit(main())
