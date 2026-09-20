from __future__ import annotations

import os
from collections import Counter
from pathlib import Path


def is_text_file(file_path, text_extensions):
    return file_path.suffix.lower() in text_extensions


def collect_top_lines(directory: str, text_extensions: set[str], top_n=500) -> None:
    for ext in text_extensions:
        lines_counter = Counter()
        for root, _, files in os.walk(directory):
            for file in files:
                file_path = Path(root) / file
                if is_text_file(file_path, text_extensions):
                    try:
                        with Path(file_path).open("r", encoding="utf-8") as f:
                            lines_counter.update(line.strip() for line in f if line.strip())
                    except (UnicodeDecodeError, PermissionError):
                        continue
        output_file = f"/sdcard/top500{ext}.txt"
        with Path(output_file).open("w", encoding="utf-8") as f:
            f.write(f"Top {top_n} most frequent lines for {ext} files:\n\n")
            f.writelines(f"{count}: {line} \n" for line, count in lines_counter.most_common(top_n))


def main() -> None:
    text_extensions = {".h", ".hpp"}
    collect_top_lines(".", text_extensions, top_n=500)


if __name__ == "__main__":
    main()
