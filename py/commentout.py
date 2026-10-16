from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tempfile import NamedTemporaryFile

COMMENT_MAP = {
    ".vim": '"',
    ".lua": "--",
    ".py": "#",
    ".sh": "#",
    ".toml": "#",
    ".yml": "#",
    ".yaml": "#",
    ".js": "//",
    ".ts": "//",
    ".cpp": "//",
    ".c": "//",
    ".cs": "//",
    ".java": "//",
    ".sql": "--",
    ".rb": "#",
}


def process_chunk(lines, comment_char):
    processed = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith(comment_char):
            processed.append(line)
        else:
            processed.append(f"{comment_char}{line}")
    return processed


def main():
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print("Usage: python commentout.py <filename> <start_line> [end_line]")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: File {path} not found.")
        sys.exit(1)
    ext = path.suffix.lower()
    comment_char = COMMENT_MAP.get(ext)
    if not comment_char:
        comment_char = "#"
        print(f"Warning: Unknown extension {ext}. Using default '#' as comment char.")
    try:
        start_line = int(sys.argv[2])
        end_line = int(sys.argv[3]) if len(sys.argv) == 4 else None
    except ValueError:
        print("Error: Line numbers must be integers.")
        sys.exit(1)
    with (
        open(path, "r", encoding="utf-8", errors="ignore") as infile,
        NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as temp_file,
    ):
        temp_path = Path(temp_file.name)
        current_line_idx = 1
        chunk_size = 10000
        with ProcessPoolExecutor() as executor:
            while True:
                lines = [infile.readline() for _ in range(chunk_size)]
                lines = [l for l in lines if l]
                if not lines:
                    break
                chunk_start = current_line_idx
                chunk_end = current_line_idx + len(lines) - 1
                target_end = end_line if end_line else float("inf")
                if chunk_start <= target_end and chunk_end >= start_line:
                    prefix_count = max(0, start_line - chunk_start)
                    suffix_start = max(0, target_end - chunk_start + 1) if end_line else len(lines)
                    prefix = lines[:prefix_count]
                    target_block = lines[prefix_count:suffix_start]
                    suffix = lines[suffix_start:]
                    future = executor.submit(process_chunk, target_block, comment_char)
                    temp_file.writelines(prefix)
                    temp_file.writelines(future.result())
                    temp_file.writelines(suffix)
                else:
                    temp_file.writelines(lines)
                current_line_idx += len(lines)
    os.replace(temp_path, path)
    print(f"Successfully processed {path} using '{comment_char}'")


if __name__ == "__main__":
    raise SystemExit(main())
