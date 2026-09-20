import json
import sys
from pathlib import Path

from dh import get_random_filename


def mergedict(da, db):
    return {**da, **db}


def load_json_object(path: Path):
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(msg)
    return data


def merge_json_files(files):
    merged = {}
    for file in files:
        path = Path(file)
        if not path.exists():
            print(f"Warning: skipping missing file {path}")
            continue
        try:
            merged = mergedict(merged, load_json_object(path))
        except Exception as e:
            print(f"Warning: {path}: {e}")
    return merged


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} file1.json file2.json [...]")
        sys.exit(1)
    args = sys.argv[1:]
    cwd = Path.cwd()
    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".json"])
    if len(files) == 1:
        print("provide more than file.")
        sys.exit(0)
    merged = merge_json_files(files)
    out_file = Path(f"{get_random_filename(6)}.json")
    if out_file.exists():
        print(f"{out_file} exists")
        sys.exit(0)
    with Path(out_file).open("w", encoding="utf-8") as fj:
        json.dump(merged, fj, indent=2, ensure_ascii=False)
    print(f"saved to {out_file}")


if __name__ == "__main__":
    main()
