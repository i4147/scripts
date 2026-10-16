from __future__ import annotations

import argparse
import os
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ssdeep
import xxhash
from tqdm import tqdm

EXCLUDE_DIRS = {".git", "__pycache__", "node_modules"}


class FileSimilarityDetector:
    def __init__(self, cwd: str = ".") -> None:
        self.cwd = Path(cwd)
        self.file_hashes = {}
        self.duplicates = defaultdict(list)

    def scan_files(self):
        for root, dirs, files in os.walk(self.cwd):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for name in files:
                yield Path(root) / name

    @staticmethod
    def hash_file(path: Path):
        try:
            data = path.read_bytes()
            return str(path), xxhash.xxh64(data).hexdigest(), ssdeep.hash(data)
        except Exception:
            return str(path), None, None

    def process_files(self, files: list[Path]) -> None:
        files = list(files)
        print(f"Processing {len(files)} files...")
        with ThreadPoolExecutor() as pool:
            futures = [pool.submit(self.hash_file, f) for f in files]
            for fut in tqdm(as_completed(futures), total=len(futures), desc="Hashing"):
                path, xh, sh = fut.result()
                if not xh or not sh:
                    continue
                self.file_hashes[path] = {"xxhash": xh, "ssdeep": sh}
                self.duplicates[xh].append(path)
        self.duplicates = {h: paths for h, paths in self.duplicates.items() if len(paths) > 1}

    def find_similarity_groups(self, threshold: int):
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

    def handle_groups(self, groups, *, move: bool, output_dir: str) -> None:
        out = Path(output_dir)
        out.mkdir(exist_ok=True)
        for idx, group in enumerate(groups, 1):
            Path(group[0])
            if move:
                for victim in group[1:]:
                    try:
                        Path(victim).unlink()
                    except Exception as e:
                        print(f"Failed to delete {victim}: {e}")
            else:
                grp_dir = out / f"similarity_group_{idx}"
                grp_dir.mkdir(exist_ok=True)
                for p in group:
                    try:
                        shutil.copy2(p, grp_dir / Path(p).name)
                    except Exception as e:
                        print(f"Failed to copy {p}: {e}")

    def print_duplicates(self) -> None:
        if not self.duplicates:
            return
        print("\n" + "=" * 40)
        print("DUPLICATES (100% identical)")
        for h, paths in self.duplicates.items():
            print(f"\nHash: {h}")
            for p in paths:
                print(f"  - {p}")
        print("-" * 40)


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect duplicate and similar files")
    parser.add_argument("threshold", type=int, help="Similarity threshold (0-100)")
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
