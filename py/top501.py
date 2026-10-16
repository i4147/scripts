import os
import time
from collections import Counter
from pathlib import Path


def is_text_file(file_path, text_extensions):
    return file_path.suffix.lower() in text_extensions


def process_file(file_path, text_extensions):
    if not is_text_file(file_path, text_extensions):
        return Counter()
    try:
        with Path(file_path).open(encoding="utf-8") as f:
            return Counter(line.strip() for line in f if line.strip())
    except (UnicodeDecodeError, PermissionError):
        return Counter()


def collect_top_lines(directory: str, text_extensions: set[str], top_n=500) -> None:
    for ext in text_extensions:
        print(f"\nProcessing {ext} files...")
        lines_counter = Counter()
        file_paths = [
            Path(root) / file
            for root, _, files in os.walk(directory)
            for file in files
            if is_text_file(Path(root) / file, {ext})
        ]
        if not file_paths:
            print(f"No {ext} files found. Skipping...")
            continue
        print(f"Found {len(file_paths)} {ext} files. Processing in parallel...")
        start_time = time.time()
        with ProcessPoolExecutor(cpu_count()) as pool:
            results = pool.starmap(
                process_file,
                [(file_path, {ext}) for file_path in file_paths],
            )
        for result in results:
            lines_counter.update(result)
        output_file = f"/sdcard/top500{ext}.txt"
        with Path(output_file).open("w", encoding="utf-8") as f:
            f.write(f"Top {top_n} most frequent lines for {ext} files:\n\n")
            f.writelines(
                f"{count}: {line}\n"
                for (
                    line,
                    count,
                ) in lines_counter.most_common(top_n)
            )
        elapsed = time.time() - start_time
        print(f"Saved top {top_n} lines for {ext} files to {output_file} (took {elapsed:.2f} seconds)")


def main() -> None:
    text_extensions = {".h", ".hpp"}
    collect_top_lines(".", text_extensions, top_n=500)


if __name__ == "__main__":
    main()
