import hashlib
import operator
from pathlib import Path
from time import perf_counter


def hash_file_chunked(filepath, chunk_size) -> str:
    sha256_hash = hashlib.sha256()
    with filepath.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def benchmark_chunk_sizes(filepath: Path):
    chunk_sizes = [2**i for i in range(10, 30)]
    results = {}
    for chunk_size in chunk_sizes:
        start_time = perf_counter()
        hash_file_chunked(filepath, chunk_size)
        end_time = perf_counter()
        results[chunk_size] = end_time - start_time
    best_chunk_size = min(results, key=results.get)
    best_time = results[best_chunk_size]
    print(f"File: {filepath.name} : ", end=" ")
    print(f"{best_chunk_size}, Time: {best_time}")
    return best_chunk_size


if __name__ == "__main__":
    results = {}
    cwd = Path.cwd()
    for path in cwd.rglob("*"):
        if path.is_dir():
            continue
        if path.is_symlink():
            continue
        if path.is_file():
            cs = benchmark_chunk_sizes(path)
            if cs not in results:
                results[cs] = 1
            else:
                results[cs] += 1
    sr = dict(sorted(results.items(), key=operator.itemgetter(1), reverse=True))
    print(sr)
