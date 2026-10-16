import multiprocessing
import sys
from pathlib import Path
from typing import List, Sequence, Set

KNOWN_SOURCE_EXTENSIONS: Set[str] = {
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".cxx",
    ".hpp",
    ".hh",
    ".hxx",
    ".cs",
    ".java",
    ".kt",
    ".kts",
    ".scala",
    ".groovy",
    ".clj",
    ".py",
    ".pyi",
    ".pyw",
    ".rb",
    ".php",
    ".pl",
    ".pm",
    ".lua",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
    ".go",
    ".rs",
    ".swift",
    ".m",
    ".mm",
    ".dart",
    ".r",
    ".jl",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".bat",
    ".cmd",
    ".sql",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".html",
    ".htm",
    ".xml",
    ".xsl",
    ".xslt",
    ".svg",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".gradle",
    ".cmake",
    ".mk",
    ".tex",
}

LARGE_FILE_THRESHOLD: int = 10000
POOL_SIZE: int = 8
CHUNKS_PER_WORKER: int = 4

_OTHER_LINES: Set[str] = set()


def _init_worker(other_lines: Set[str]) -> None:
    global _OTHER_LINES
    _OTHER_LINES = other_lines


def _filter_chunk(chunk: Sequence[str]) -> List[str]:
    other = _OTHER_LINES
    return [line for line in chunk if line not in other]


def read_lines(path: Path) -> List[str]:
    strip_whitespace = path.suffix.lower() in KNOWN_SOURCE_EXTENSIONS
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        raw_lines = handle.readlines()
    lines: List[str] = []
    for raw in raw_lines:
        line = raw.rstrip("\n").rstrip("\r")
        if strip_whitespace:
            line = line.strip(" \t")
        lines.append(line)
    return lines


def compute_only_in_first(
    lines1: Sequence[str],
    lines2: Sequence[str],
    set1: Set[str],
    set2: Set[str],
) -> Set[str]:
    if len(lines1) > LARGE_FILE_THRESHOLD and len(lines2) > LARGE_FILE_THRESHOLD:
        chunk_size = max(1, len(lines1) // (POOL_SIZE * CHUNKS_PER_WORKER))
        chunks = [list(lines1[i : i + chunk_size]) for i in range(0, len(lines1), chunk_size)]
        collected: Set[str] = set()
        with multiprocessing.Pool(
            processes=POOL_SIZE,
            initializer=_init_worker,
            initargs=(set2,),
        ) as pool:
            for partial in pool.imap_unordered(_filter_chunk, chunks):
                collected.update(partial)
        return collected
    return set1 - set2


def main(argv: Sequence[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {Path(argv[0]).name} FILE1 FILE2", file=sys.stderr)
        return 2

    path1 = Path(argv[1])
    path2 = Path(argv[2])

    for path in (path1, path2):
        if not path.is_file():
            print(f"error: not a regular file: {path}", file=sys.stderr)
            return 1

    try:
        lines1 = read_lines(path1)
        lines2 = read_lines(path2)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    set1: Set[str] = set(lines1)
    set2: Set[str] = set(lines2)

    common = set1 & set2
    only1 = compute_only_in_first(lines1, lines2, set1, set2)
    only2 = set2 - set1

    print(f"only in {path1}:")
    for line in sorted(only1):
        print(line)
    print()

    print(f"only in {path2}:")
    for line in sorted(only2):
        print(line)
    print()

    print("summary:")
    print(f"  {path1}: {len(lines1)} lines read, {len(set1)} unique")
    print(f"  {path2}: {len(lines2)} lines read, {len(set2)} unique")
    print(f"  common lines: {len(common)}")
    print(f"  only in {path1}: {len(only1)}")
    print(f"  only in {path2}: {len(only2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
