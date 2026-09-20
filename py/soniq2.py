from __future__ import annotations

import mmap
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MB_5 = 5 * 1024 * 1024


def sort_and_uniq(file_path: str) -> None:
    if not Path(file_path).exists():
        print(f"Error: File '{file_path}' not found.")
        return
    try:
        get_size = Path(file_path).stat().st_size
        lines = []
        if get_size > MB_5:
            with (
                Path(file_path).open("r+b") as f,
                mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm,
            ):
                lines = mm.read().decode("utf-8").splitlines()
        else:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        with ThreadPoolExecutor() as executor:
            processed_lines = list(executor.map(lambda x: x.strip(), lines))
        unique_sorted_lines = sorted(set(processed_lines))
        fd, temp_path = tempfile.mkstemp(dir=Path(file_path).parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                for line in unique_sorted_lines:
                    tmp.write(line + "\n")
            Path(temp_path).replace(file_path)
            print(f"Successfully updated '{file_path}'.")
        except Exception:
            Path(temp_path).unlink()
            raise
    except Exception as e:
        print(f"Failed to process file: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <filename>")
    else:
        sort_and_uniq(sys.argv[1])
