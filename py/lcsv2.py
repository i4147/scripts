import csv
import os
import pathlib
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm


def process_file(filepath):
    counter = Counter()
    try:
        with pathlib.Path(filepath).open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line:
                    counter[line] += 1
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    return counter


def collect_lines_for_extension(ext: str) -> None:
    files = []
    for root, _dirs, filenames in os.walk(pathlib.Path.cwd()):
        files.extend(os.path.join(root, fname) for fname in filenames if fname.lower().endswith(f".{ext.lower()}"))
    if not files:
        print(f"No files found for extension: {ext}")
        return
    global_counter = Counter()
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(process_file, f): f for f in files}
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc=f"Processing .{ext} files",
        ):
            global_counter.update(future.result())
    output_file = f"{ext}.csv"
    with pathlib.Path(output_file).open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["number_of_appearance", "line"])
        for (
            line,
            count,
        ) in global_counter.most_common():
            if count > 1:
                writer.writerow([count, line])
    print(f"Saved results to {output_file}")


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <ext1> [ext2] ...")
        sys.exit(1)
    extensions = sys.argv[1:]
    for ext in extensions:
        collect_lines_for_extension(ext)


if __name__ == "__main__":
    main()
