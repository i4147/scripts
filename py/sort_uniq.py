import sys
from pathlib import Path

THRESHOLD = 5242880


def sort_uniq(path: Path) -> None:
    file_size = path.stat().st_size
    if file_size > THRESHOLD:
        import mmap

        with path.open(encoding="utf-8", errors="ignore") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                lines = mm.read().decode("utf-8").splitlines()
    else:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    unique_lines = sorted({line.strip() for line in lines if line.strip()})
    removed_num = len(lines) - len(unique_lines)
    if removed_num > 0:
        path.write_text("\n".join(unique_lines))
        print(f"{path.name}: {removed_num} lines removed")
    else:
        print(f"{path.name} no change")


if __name__ == "__main__":
    path = Path(sys.argv[1])
    sort_uniq(path)
