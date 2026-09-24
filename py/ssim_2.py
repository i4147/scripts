import argparse
import shutil
from collections.abc import Iterator
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import List
import ssdeep
import xxhash
from loguru import logger
from tqdm import tqdm

EXCLUDE_DIRS = {".git", "__pycache__", "node_modules"}


def hash_file(path):
    try:
        data = path.read_bytes()
        return str(path), xxhash.xxh64(data).hexdigest(), ssdeep.hash(data)
    except Exception as e:
        logger.error(f"Error hashing {path}: {e}")
        return str(path), None, None


class FileSimilarityDetector:
    def __init__(self, cwd="."):
        self.cwd = Path(cwd)
        self.file_hashes = {}
        self.duplicates = {}

    def scan_files(self):
        for path in self.cwd.rglob("*"):
            if path.is_file() and not path.is_symlink():
                if not any(part in EXCLUDE_DIRS for part in path.parts):
                    yield path

    def process_files(self, files):
        print(f"Processing {len(files)} files...")
        with Pool(processes=8) as pool:
            async_results = [pool.apply_async(hash_file, (f,)) for f in files]
            for async_res in tqdm(async_results, total=len(async_results), desc="Hashing"):
                path, xh, sh = async_res.get()
                if not xh or not sh:
                    continue
                self.file_hashes[path] = {"xxhash": xh, "ssdeep": sh}
                self.duplicates.setdefault(xh, []).append(path)
        self.duplicates = {h: paths for h, paths in self.duplicates.items() if len(paths) > 1}

    def find_similarity_groups(self, threshold):
        excluded = {p for group in self.duplicates.values() for p in group}
        candidates = [p for p in self.file_hashes if p not in excluded]
        visited = set()
        groups = []
        for i, p1 in enumerate(tqdm(candidates, desc="Finding Similarities")):
            if p1 in visited:
                continue
            group = [p1]
            visited.add(p1)
            h1 = self.file_hashes[p1]["ssdeep"]
            for p2 in candidates[i + 1 :]:
                if p2 in visited:
                    continue
                if ssdeep.compare(h1, self.file_hashes[p2]["ssdeep"]) >= threshold:
                    group.append(p2)
                    visited.add(p2)
            if len(group) > 1:
                groups.append(group)
        return groups

    def handle_groups(self, groups, *, move, output_dir):
        out = Path(output_dir)
        out.mkdir(exist_ok=True)
        for idx, group in enumerate(groups, 1):
            if move:
                for victim in group[1:]:
                    try:
                        Path(victim).unlink()
                        print(f"Deleted {victim}")
                    except Exception as e:
                        logger.error(f"Failed to delete {victim}: {e}")
            else:
                grp_dir = out / f"similarity_group_{idx}"
                grp_dir.mkdir(exist_ok=True)
                for p in group:
                    try:
                        shutil.copy2(p, grp_dir / Path(p).name)
                        print(f"Copied {p} to {grp_dir}")
                    except Exception as e:
                        logger.error(f"Failed to copy {p}: {e}")

    def print_duplicates(self):
        if not self.duplicates:
            return
        print("=" * 40)
        print("DUPLICATES (100% identical)")
        for h, paths in self.duplicates.items():
            print(f"\nHash: {h}")
            for p in paths:
                print(f"  - {p}")
        print("-" * 40)


def main():
    parser = argparse.ArgumentParser(description="Detect duplicate and similar files")
    parser.add_argument("threshold", type=int, default=70, help="Similarity threshold (0-100)")
    parser.add_argument(
        "-m",
        "--move",
        action="store_true",
        help="Keep one file per similarity group and delete the rest",
    )
    parser.add_argument("-o", "--output", default="output", help="Output directory (copy mode only)")
    args = parser.parse_args()
    detector = FileSimilarityDetector()
    files = list(detector.scan_files())
    if not files:
        print("No files found.")
        return
    detector.process_files(files)
    groups = detector.find_similarity_groups(args.threshold)
    if groups:
        detector.handle_groups(groups, move=args.move, output_dir=args.output)
        print(f"Processed {len(groups)} similarity groups.")
    else:
        print("No similar (non-identical) files found.")
    detector.print_duplicates()


if __name__ == "__main__":
    raise SystemExit(main())
