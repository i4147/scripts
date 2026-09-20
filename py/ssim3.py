import csv
import json
import operator
import os
import pathlib
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import ssdeep

try:
    USE_TABULATE = True
except ImportError:
    USE_TABULATE = False
try:
    from colorama import init

    init(autoreset=True)
    USE_COLOR = True
except ImportError:
    USE_COLOR = False


def get_all_files(root: str = "."):
    file_paths = []
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for f in filenames:
            full_path = os.path.join(dirpath, f)
            file_paths.append(full_path)
    return file_paths


def compute_hash(file_path):
    try:
        with pathlib.Path(file_path).open("rb") as fh:
            data = fh.read()
            return file_path, ssdeep.hash(data)
    except Exception as e:
        print(f"Skipping {file_path}: {e}")
        return file_path, None


def compute_hashes(files):
    hashes = {}
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(compute_hash, f): f for f in files}
        for future in as_completed(futures):
            f, h = future.result()
            if h:
                hashes[f] = h
    return hashes


def compare_pair(f1, h1, f2, h2):
    score = ssdeep.compare(h1, h2)
    return (f1, f2, score)


def summarize_top_pairs(hashes, threshold: int, top_n: int = 10):
    files = list(hashes.keys())
    pairs = []
    with ThreadPoolExecutor() as executor:
        futures = []
        for i, f1 in enumerate(files):
            futures.extend(
                executor.submit(
                    compare_pair,
                    f1,
                    hashes[f1],
                    f2,
                    hashes[f2],
                )
                for f2 in files[i + 1 :]
            )
        for future in as_completed(futures):
            f1, f2, score = future.result()
            if score >= threshold:
                pairs.append((f1, f2, score))
    pairs.sort(key=operator.itemgetter(2), reverse=True)
    return pairs[:top_n]


def group_similar_files(hashes, threshold: int):
    visited = set()
    groups = []
    files = list(hashes.keys())
    for i, f1 in enumerate(files):
        if f1 in visited:
            continue
        group = [f1]
        visited.add(f1)
        for f2 in files[i + 1 :]:
            if f2 in visited:
                continue
            score = ssdeep.compare(hashes[f1], hashes[f2])
            if score >= threshold:
                group.append(f2)
                visited.add(f2)
        if len(group) > 1:
            groups.append(group)
    return groups


def copy_groups(groups, output_dir="output") -> None:
    pathlib.Path(output_dir).mkdir(exist_ok=True, parents=True)
    for idx, group in enumerate(groups, start=1):
        group_dir = os.path.join(output_dir, f"group_{idx}")
        pathlib.Path(group_dir).mkdir(exist_ok=True, parents=True)
        for f in group:
            try:
                shutil.copy2(f, group_dir)
            except Exception as e:
                print(f"Failed to copy {f}: {e}")


def export_top_pairs(pairs, format="csv", output_dir="output") -> None:
    pathlib.Path(output_dir).mkdir(exist_ok=True, parents=True)
    if format == "csv":
        report_file = os.path.join(output_dir, "top_pairs.csv")
        with pathlib.Path(report_file).open("w", encoding="utf-8", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["File1", "File2", "Score"])
            for f1, f2, score in pairs:
                writer.writerow([f1, f2, score])
        print(f"Top pairs CSV written to {report_file}")
    elif format == "json":
        report_file = os.path.join(output_dir, "top_pairs.json")
        data = [
            {
                "file1": f1,
                "file2": f2,
                "score": score,
            }
            for f1, f2, score in pairs
        ]
        with pathlib.Path(report_file).open("w", encoding="utf-8") as jf:
            json.dump(data, jf, indent=2)
        print(f"Top pairs JSON written to {report_file}")


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <threshold> [copy|csv|json|matrix] [topN] [exportFormat]")
        sys.exit(1)
    try:
        threshold = int(sys.argv[1])
    except ValueError:
        print("Threshold must be an integer (0–100).")
        sys.exit(1)
    mode = sys.argv[2] if len(sys.argv) > 2 else "copy"
    top_n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    export_format = sys.argv[4] if len(sys.argv) > 4 else None
    files = get_all_files(".")
    print(f"Found {len(files)} files (excluding .git). Computing hashes in parallel...")
    hashes = compute_hashes(files)
    print("Comparing files...")
    groups = group_similar_files(hashes, threshold)
    if not groups and mode != "matrix":
        print("No similar files found.")
    elif mode == "copy":
        print(f"Found {len(groups)} groups of similar files.")
        copy_groups(groups)
        print("Copied groups to 'output' directory.")
    elif mode in {"csv", "json"}:
        print(f"Found {len(groups)} groups of similar files.")
    elif mode == "matrix":
        top_pairs = summarize_top_pairs(hashes, threshold, top_n)
        print(f"\nTop {top_n} similar pairs:")
        for f1, f2, score in top_pairs:
            print(f"{f1} <--> {f2} : {score}")
        if export_format:
            export_top_pairs(top_pairs, format=export_format)
    else:
        print("Unknown mode. Use 'copy', 'csv', 'json', or 'matrix'.")


if __name__ == "__main__":
    main()
