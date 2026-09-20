import sys
from pathlib import Path
from dh import get_pyfiles


def process_file(fp: Path) -> bool:
    try:
        print(f"processing {fp}")
        lines = []
        newlines = []
        with Path(fp).open(encoding="utf-8") as fin:
            lines = fin.readlines()
        for line in lines[1:]:
            newlines.append(line)
        with Path(fp).open("w", encoding="utf-8") as fout:
            fout.writelines(newlines)
        return True
    except:
        return False


def main() -> None:
    dir = Path.cwd()
    filez = get_pyfiles(dir)
    for file in filez:
        path = Path(file)
        f1 = path.read_text(encoding="utf-8").splitlines()[0]
        if "#!" in f1:
            process_file(path)


if __name__ == "__main__":
    sys.exit(main())
