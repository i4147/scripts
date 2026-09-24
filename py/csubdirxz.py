import tarfile
import shutil
from pathlib import Path
from multiprocessing import Pool


XZ_COMPRESSION_LEVEL = 9
WORKERS = 8


import lzma
import tarfile
from pathlib import Path


def compress_subdir(subdir: Path) -> tuple[Path, bool, str]:
    archive_path = subdir.with_suffix(subdir.suffix + ".tar.xz")

    try:
        with lzma.LZMAFile(archive_path, mode="wb", preset=9) as lzma_file:
            with tarfile.open(fileobj=lzma_file, mode="w") as tar:
                tar.add(subdir, arcname=subdir.name)

        if not archive_path.is_file() or archive_path.stat().st_size == 0:
            return (subdir, False, f"Archive {archive_path.name} is missing or empty")

        shutil.rmtree(subdir)
        return (subdir, True, f"Compressed {subdir.name} -> {archive_path.name}")

    except Exception as exc:
        if archive_path.exists():
            archive_path.unlink()
        return (subdir, False, f"Failed {subdir.name}: {exc}")


def main() -> None:
    cwd = Path.cwd()

    subdirs = sorted(
        [entry for entry in cwd.iterdir() if entry.is_dir()],
        key=lambda p: p.name.lower(),
    )

    if not subdirs:
        print("No top-level subdirectories found in", cwd)
        return

    print(f"Found {len(subdirs)} subdirectories to compress in {cwd}")
    print(f"Using {WORKERS} workers, xz level {XZ_COMPRESSION_LEVEL}\n")

    results = []
    with Pool(processes=WORKERS) as pool:
        async_results = [pool.apply_async(compress_subdir, (subdir,)) for subdir in subdirs]

        for async_result in async_results:
            results.append(async_result.get())

    successes = failures = 0
    for subdir, success, message in results:
        print(message)
        if success:
            successes += 1
        else:
            failures += 1

    print(f"\nDone: {successes} succeeded, {failures} failed.")


if __name__ == "__main__":
    main()
