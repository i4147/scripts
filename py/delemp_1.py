import sys
import tempfile
from pathlib import Path
from dh import cprint, fsz, get_nobinary, gsz, mpf3


def process_file(path: (str | Path)) -> int:
    path = Path(path)
    if path.is_symlink() or path.suffix == ".bak" or gsz(path) == 0:
        return 0
    removed_count = 0
    try:
        temp_file_path = None
        with tempfile.NamedTemporaryFile(
            mode="w+", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
        ) as temp_f:
            temp_file_path = Path(temp_f.name)
            with path.open("r", encoding="utf-8", errors="replace") as original_f:
                for line in original_f:
                    if line.strip():
                        temp_f.write(line)
                    else:
                        removed_count += 1
        if not removed_count:
            temp_file_path.unlink()
            cprint(f"[NOCHANGE] {path.name}", "green")
            return 0
        Path(temp_file_path).replace(path)
        print(f"[OK] {path.name}", end=" | ")
        cprint(f"{removed_count}", "cyan")
        return removed_count
    except OSError:
        if temp_file_path and temp_file_path.exists():
            temp_file_path.unlink()
        return 0
    except Exception as e:
        if temp_file_path and temp_file_path.exists():
            temp_file_path.unlink()
        print(f"An unexpected error occurred processing {path.name}: {e}")
        return 0


def main() -> None:
    files = []
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(arg) for arg in args] if args else get_nobinary(cwd)
    print(f"{len(files)} files found")
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)
    lines_removed = 0
    results = mpf3(process_file, files)
    for result in results:
        if result:
            lines_removed += result
    cprint(f"total removed : {lines_removed}", "green")
    diffsize = before - gsz(cwd)
    print("space freed: ", end="")
    cprint(f"{fsz(diffsize)}", "cyan")


if __name__ == "__main__":
    sys.exit(main())
