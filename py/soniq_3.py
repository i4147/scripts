import mmap
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

COLOR_RED = "\033[91m"
COLOR_RESET = "\033[0m"
COLOR_YELLOW = "\033[93m"
THRESHOLD = 10 * 1024 * 1024


def is_binary(path: Path, blocksize=4096) -> bool:
    with path.open("rb") as f:
        sample = f.read(blocksize)
    if b"\x00" in sample:
        return True
    text_chars = bytes(range(32, 127)) + b"\n\r\t\b"
    nontext = sum(c not in text_chars for c in sample)
    return nontext / max(len(sample), 1) > 0.30


def _process_chunk(chunk: list[str]) -> list[str]:
    return [p.strip() for p in chunk if p.strip()]


def read_lines(path: Path) -> list[str]:
    sz = path.stat().st_size
    if sz > THRESHOLD:
        with (
            path.open("r", encoding="utf-8", errors="ignore") as f,
            mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm,
        ):
            data = mm.read().decode("utf-8", "ignore")
            return data.splitlines()
    else:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def sort_uniq(path: Path, show_diff: bool = True) -> int:
    lines = read_lines(path)
    original_count = len(lines)
    if not original_count:
        return 0
    if original_count > 100000:
        num_workers = max(1, cpu_count() - 1)
        chunk_size = len(lines) // num_workers + 1
        chunks = [lines[i : i + chunk_size] for i in range(0, len(lines), chunk_size)]
        with Pool(num_workers) as pool:
            processed = pool.map(_process_chunk, chunks)
        all_lines = [line for group in processed for line in group]
    else:
        all_lines = [p.strip() for p in lines if p.strip()]
    unique_sorted_set = set(all_lines)
    unique_sorted = sorted(unique_sorted_set)
    removed_lines_set = set(all_lines) - unique_sorted_set
    lines_removed_count = original_count - len(unique_sorted_set)
    path.write_text("\n".join(unique_sorted), encoding="utf-8")
    if show_diff and removed_lines_set:
        print(f"\n{COLOR_YELLOW}Duplicate lines removed ({lines_removed_count}):{COLOR_RESET}")
        sorted_removed_lines = sorted(list(removed_lines_set))
        preview_limit = 50
        for line in sorted_removed_lines[:preview_limit]:
            print(f"{COLOR_RED}  - {line}{COLOR_RESET}")
        if len(sorted_removed_lines) > preview_limit:
            print(f"{COLOR_YELLOW}  ... ({len(sorted_removed_lines) - preview_limit} more not shown){COLOR_RESET}")
    elif show_diff and not removed_lines_set:
        print(f"\n{COLOR_YELLOW}No duplicate lines were removed.{COLOR_RESET}")
    return lines_removed_count


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sort_uniq_mp.py <filename> [--diff]")
        sys.exit(1)
    show_diff = "--diff" in sys.argv
    filename_arg = next((a for a in sys.argv[1:] if not a.startswith("--")), None)
    if not filename_arg:
        print("Error: missing filename argument.")
        sys.exit(1)
    path = Path(filename_arg)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)
    if is_binary(path):
        print(f"{path.name} is binary. Skipped.")
        sys.exit(0)
    removed_count = sort_uniq(path, show_diff)
    if removed_count > 0:
        print(f"\n{COLOR_YELLOW}Successfully removed {removed_count} duplicate lines.{COLOR_RESET}")
    elif not show_diff:
        print("No change.")
