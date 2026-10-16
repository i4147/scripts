#!/data/data/com.termux/files/usr/bin/python
import argparse
from collections import defaultdict
import json
import operator
from pathlib import Path
from dh import get_files

try:
    import tlsh
except ImportError:
    tlsh = None

try:
    import ssdeep
except ImportError:
    ssdeep = None


# TLSH requires at least this much input to produce a meaningful hash.
TLSH_MIN_DATA_LENGTH = 50


def calculate_ssdeep_hash(path: Path, min_file_size: int = 1):
    if ssdeep is None:
        raise RuntimeError("ssdeep module is not installed (`pip install ssdeep`)")
    try:
        if path.stat().st_size < min_file_size:
            return None
        with path.open("rb") as f:
            data = f.read()
            if len(data) < min_file_size:
                return None
            return ssdeep.hash(data)
    except FileNotFoundError:
        print(f"Error: File not found at {path}")
        return None
    except OSError as e:
        print(f"OS error accessing {path}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred for {path}: {e}")
        return None


def calculate_tlsh_hash(path: Path, min_file_size: int = TLSH_MIN_DATA_LENGTH):
    if tlsh is None:
        raise RuntimeError("tlsh module is not installed (`pip install tlsh`)")
    try:
        if path.stat().st_size < min_file_size:
            return None
        h = tlsh.Tlsh()
        total = 0
        with path.open("rb") as f:
            for buf in iter(lambda: f.read(4096), b""):
                h.update(buf)
                total += len(buf)
        if total < min_file_size:
            return None
        h.final()
        return h.hexdigest()
    except FileNotFoundError:
        print(f"Error: File not found at {path}")
        return None
    except OSError as e:
        print(f"OS error accessing {path}: {e}")
        return None
    except ValueError:
        # tlsh raises ValueError when input is too small / too low entropy.
        return None
    except Exception as e:
        print(f"An unexpected error occurred for {path}: {e}")
        return None


def calculate_hash(path: Path, alg: str):
    if alg == "tlsh":
        return calculate_tlsh_hash(path)
    if alg == "ssdeep":
        return calculate_ssdeep_hash(path)
    raise ValueError(f"Unknown algorithm: {alg}")


def compare_hashes(hash1, hash2, alg: str) -> int:
    """Return a similarity score in [0, 100] where 100 means identical."""
    if alg == "tlsh":
        # tlsh.diff: 0 = identical, larger = more different.
        # Convert to a ssdeep-style similarity so thresholds behave the same.
        distance = tlsh.diff(hash1, hash2)
        return max(0, 100 - distance)
    if alg == "ssdeep":
        return ssdeep.compare(hash1, hash2)
    raise ValueError(f"Unknown algorithm: {alg}")


def compare_files(paths: list[Path], alg: str, similarity_threshold: int = 70):
    file_hashes = {}
    for path in paths:
        file_hash = calculate_hash(path, alg)
        if file_hash:
            file_hashes[str(path)] = file_hash

    similarities = []
    cwd = Path.cwd()
    paths_list = list(file_hashes.keys())
    for i in range(len(paths_list)):
        for j in range(i + 1, len(paths_list)):
            path1_str = paths_list[i]
            path2_str = paths_list[j]
            hash1 = file_hashes[path1_str]
            hash2 = file_hashes[path2_str]
            try:
                score = compare_hashes(hash1, hash2, alg)
                if score >= similarity_threshold:
                    similarities.append({
                        "file1": str(Path(path1_str).relative_to(cwd)),
                        "file2": str(Path(path2_str).relative_to(cwd)),
                        "similarity_score": score,
                    })
            except Exception as e:
                print(f"Error comparing hashes for {path1_str} and {path2_str}: {e}")

    similarities.sort(key=operator.itemgetter("similarity_score"), reverse=True)
    return similarities


def save_to_json(data, filename: str = "simz.json") -> None:
    try:
        with Path(filename).open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving data to JSON file '{filename}': {e}")


def strip_one_suffix(name: str) -> str:
    p = Path(name)
    if p.stem.endswith("_1"):
        return p.stem[:-2] + p.suffix
    return name


def are_related(a: str, b: str) -> bool:
    return strip_one_suffix(a) == b or strip_one_suffix(b) == a


def group_similar(json_file: str = "simz.json") -> None:
    cwd = Path.cwd()
    simz = cwd / json_file
    if not simz.exists():
        print(f"{simz} not found")
        return
    try:
        records = json.loads(simz.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error reading {simz}: {e}")
        return
    files = set()
    for rec in records:
        files.add(rec["file1"])
        files.add(rec["file2"])
    parent = {f: f for f in files}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for rec in records:
        a, b = rec["file1"], rec["file2"]
        if are_related(a, b):
            union(a, b)
    clusters_by_root = defaultdict(list)
    for f in files:
        clusters_by_root[find(f)].append(f)
    clusters = [sorted(g) for g in clusters_by_root.values() if len(g) > 1]
    clusters.sort()
    for idx, cluster in enumerate(clusters, start=1):
        subdir = cwd / f"group{idx:03d}"
        subdir.mkdir(exist_ok=True)
        for name in cluster:
            src = cwd / name
            dst = subdir / name
            if not src.exists():
                print(f"[skip] {name}: not found in {cwd}")
                continue
            if dst.exists():
                print(f"[skip] {name}: already exists at {dst}")
                continue
            src.rename(dst)
            print(f"[move] {name} -> {subdir.name}/")
    print(f"\nDone. Created {len(clusters)} group(s).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-g",
        "--group-similar",
        action="store_true",
        help="Move similar files into group001, group002, ... subdirs based on simz.json",
    )
    parser.add_argument(
        "-a",
        "--alg",
        choices=["tlsh", "ssdeep"],
        default="tlsh",
        help="Hashing algorithm to use (default: tlsh)",
    )
    args = parser.parse_args()

    if args.alg == "tlsh" and tlsh is None:
        parser.error("tlsh is not installed. Install it with `pip install tlsh`.")
    if args.alg == "ssdeep" and ssdeep is None:
        parser.error("ssdeep is not installed. Install it with `pip install ssdeep`.")

    cwd = Path.cwd()
    MIN_SIMILARITY_THRESHOLD = 0
    OUTPUT_JSON_FILE = "simz.json"
    files = get_files(cwd)
    if not files:
        print("No files found matching the criteria in the specified directory.")
    else:
        print(f"Using algorithm: {args.alg}")
        similar_file_pairs = compare_files(files, args.alg, MIN_SIMILARITY_THRESHOLD)
        if similar_file_pairs:
            save_to_json(similar_file_pairs, OUTPUT_JSON_FILE)
        else:
            print(f"\nNo files found with similarity >= {MIN_SIMILARITY_THRESHOLD}%.")
    if args.group_similar:
        group_similar(OUTPUT_JSON_FILE)


if __name__ == "__main__":
    main()
