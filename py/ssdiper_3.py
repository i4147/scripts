#!/data/data/com.termux/files/usr/bin/python
import argparse
from collections import defaultdict
import json
import operator
from pathlib import Path
from typing import Callable, Optional
from dh import get_files

try:
    import tlsh
except ImportError:
    tlsh = None
try:
    import ssdeep
except ImportError:
    ssdeep = None
try:
    from sdhash import sdhash as _sdhash_hash, compare as _sdhash_compare
except ImportError:
    _sdhash_hash = None
    _sdhash_compare = None
try:
    from simhash import Simhash
except ImportError:
    Simhash = None
try:
    from datasketch import MinHash
except ImportError:
    MinHash = None
TLSH_MIN_DATA_LENGTH = 50
MINHASH_NUM_PERM = 128
MINHASH_SHINGLE_SIZE = 5
SIMHASH_SHINGLE_SIZE = 3


def calculate_ssdeep_hash(path: Path, min_file_size: int = 1) -> Optional[str]:
    if ssdeep is None:
        raise RuntimeError("ssdeep module is not installed")
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


def calculate_tlsh_hash(path: Path, min_file_size: int = TLSH_MIN_DATA_LENGTH) -> Optional[str]:
    if tlsh is None:
        raise RuntimeError("tlsh module is not installed")
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
        return None
    except Exception as e:
        print(f"An unexpected error occurred for {path}: {e}")
        return None


def calculate_sdhash_hash(path: Path, min_file_size: int = 1) -> Optional[str]:
    if _sdhash_hash is None:
        raise RuntimeError("sdhash module is not installed")
    try:
        if path.stat().st_size < min_file_size:
            return None
        with path.open("rb") as f:
            data = f.read()
            if len(data) < min_file_size:
                return None
            return _sdhash_hash(data)
    except FileNotFoundError:
        print(f"Error: File not found at {path}")
        return None
    except OSError as e:
        print(f"OS error accessing {path}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred for {path}: {e}")
        return None


def _shingles(data: bytes, k: int) -> list[bytes]:
    if len(data) < k:
        return [data] if data else []
    return [data[i : i + k] for i in range(len(data) - k + 1)]


def calculate_minhash_hash(path: Path, min_file_size: int = 1) -> Optional[str]:
    if MinHash is None:
        raise RuntimeError("datasketch module is not installed")
    try:
        if path.stat().st_size < min_file_size:
            return None
        with path.open("rb") as f:
            data = f.read()
        if len(data) < min_file_size:
            return None
        m = MinHash(num_perm=MINHASH_NUM_PERM)
        for shingle in _shingles(data, MINHASH_SHINGLE_SIZE):
            m.update(shingle)
        return json.dumps(m.hashvalues.tolist())
    except FileNotFoundError:
        print(f"Error: File not found at {path}")
        return None
    except OSError as e:
        print(f"OS error accessing {path}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred for {path}: {e}")
        return None


def calculate_simhash_hash(path: Path, min_file_size: int = 1) -> Optional[str]:
    if Simhash is None:
        raise RuntimeError("simhash module is not installed")
    try:
        if path.stat().st_size < min_file_size:
            return None
        with path.open("rb") as f:
            data = f.read()
        if len(data) < min_file_size:
            return None
        features = _shingles(data, SIMHASH_SHINGLE_SIZE)
        if not features:
            return None
        return str(Simhash(features).value)
    except FileNotFoundError:
        print(f"Error: File not found at {path}")
        return None
    except OSError as e:
        print(f"OS error accessing {path}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred for {path}: {e}")
        return None


def compare_tlsh(hash1: str, hash2: str) -> int:
    if tlsh is None:
        raise RuntimeError("tlsh module is not installed")
    distance = tlsh.diff(hash1, hash2)
    return max(0, 100 - distance)


def compare_ssdeep(hash1: str, hash2: str) -> int:
    if ssdeep is None:
        raise RuntimeError("ssdeep module is not installed")
    return ssdeep.compare(hash1, hash2)


def compare_sdhash(hash1: str, hash2: str) -> int:
    if _sdhash_compare is None:
        raise RuntimeError("sdhash module is not installed")
    return int(_sdhash_compare(hash1, hash2))


def compare_minhash(hash1: str, hash2: str) -> int:
    if MinHash is None:
        raise RuntimeError("datasketch module is not installed")
    import numpy as np

    a = np.array(json.loads(hash1), dtype=np.uint64)
    b = np.array(json.loads(hash2), dtype=np.uint64)
    if a.size == 0 or b.size == 0 or a.size != b.size:
        return 0
    return int(round(100.0 * float((a == b).sum()) / float(a.size)))


def compare_simhash(hash1: str, hash2: str) -> int:
    a = int(hash1)
    b = int(hash2)
    hamming = bin(a ^ b).count("1")
    return max(0, 100 - int(round(100.0 * hamming / 64.0)))


HashFn = Callable[[Path], Optional[str]]
CompareFn = Callable[[str, str], int]
ALGORITHMS: dict[str, tuple[HashFn, CompareFn, Optional[object]]] = {
    "tlsh": (calculate_tlsh_hash, compare_tlsh, tlsh),
    "ssdeep": (calculate_ssdeep_hash, compare_ssdeep, ssdeep),
    "sdhash": (calculate_sdhash_hash, compare_sdhash, _sdhash_hash),
    "minhash": (calculate_minhash_hash, compare_minhash, MinHash),
    "simhash": (calculate_simhash_hash, compare_simhash, Simhash),
}


def calculate_hash(path: Path, alg: str) -> Optional[str]:
    if alg not in ALGORITHMS:
        raise ValueError(f"Unknown algorithm: {alg}")
    hash_fn, _, _ = ALGORITHMS[alg]
    return hash_fn(path)


def compare_hashes(hash1: str, hash2: str, alg: str) -> int:
    if alg not in ALGORITHMS:
        raise ValueError(f"Unknown algorithm: {alg}")
    _, compare_fn, _ = ALGORITHMS[alg]
    return compare_fn(hash1, hash2)


def compare_files(
    paths: list[Path],
    alg: str,
    similarity_threshold: int = 70,
) -> list[dict[str, object]]:
    file_hashes: dict[str, str] = {}
    for path in paths:
        file_hash = calculate_hash(path, alg)
        if file_hash:
            file_hashes[str(path)] = file_hash
    similarities: list[dict[str, object]] = []
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


def save_to_json(data: object, filename: str = "simz.json") -> None:
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
    files: set[str] = set()
    for rec in records:
        files.add(rec["file1"])
        files.add(rec["file2"])
    parent: dict[str, str] = {f: f for f in files}

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
    clusters_by_root: dict[str, list[str]] = defaultdict(list)
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
        choices=list(ALGORITHMS.keys()),
        default="tlsh",
        help="Hashing algorithm to use (default: tlsh)",
    )
    args = parser.parse_args()
    _, _, module = ALGORITHMS[args.alg]
    if module is None:
        parser.error(
            f"{args.alg} is not installed. "
            f"Install it with `pip install {args.alg if args.alg != 'sdhash' else 'pysdhash'}`."
        )
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
