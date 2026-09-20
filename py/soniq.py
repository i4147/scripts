import mmap
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

THRESHOLD = 1024 * 1024


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


def sort_uniq(path: Path, show_diff: bool = False) -> int:
    lines = read_lines(path)
    original_count = len(lines)
    if not original_count:
        return 0
    if original_count > 1000:
        num_workers = max(1, cpu_count() - 1)
        chunk_size = len(lines) // num_workers + 1
        chunks = [lines[i : i + chunk_size] for i in range(0, len(lines), chunk_size)]
        with Pool(num_workers) as pool:
            processed = pool.map(_process_chunk, chunks)
        all_lines = [line for group in processed for line in group]
    else:
        all_lines = [p.strip() for p in lines if p.strip()]
    unique_sorted = sorted(set(all_lines))
    diff_lines = set(all_lines) - set(unique_sorted)
    lines_removed = original_count - len(unique_sorted)
    path.write_text("\n".join(unique_sorted), encoding="utf-8")
    if show_diff and diff_lines:
        print("\nDuplicate lines removed:")
        for line in list(sorted(diff_lines))[:50]:
            print("  " + line)
        if len(diff_lines) > 50:
            print(f"... ({len(diff_lines) - 50} more not shown)")
    return lines_removed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sort_uniq_mp.py <filename> [--diff]")
        sys.exit(1)
    show_diff = True
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
    removed = sort_uniq(path, show_diff)
    if removed > 0:
        print(f"\nRemoved {removed} duplicate lines.")
    else:
        print("No change.")
