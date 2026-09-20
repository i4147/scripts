from __future__ import annotations

import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def check_integrity(archive_path: Path) -> tuple[bool, str]:
    try:
        if not tarfile.is_tarfile(archive_path):
            return False, f"Invalid tar format: {archive_path.name}"
        with tarfile.open(archive_path, "r:*") as tar:
            tar.getmembers()
        return True, f"Valid: {archive_path.name}"
    except (tarfile.TarError, EOFError) as e:
        return False, f"Corrupted: {archive_path.name} - {type(e).__name__}"
    except Exception as e:
        return False, f"Check failed: {archive_path.name} - {e}"


def extract_archive(archive_path: Path) -> tuple[Path, bool, str]:
    try:
        with tarfile.open(archive_path, "r:*") as tar:
            tar.extractall(path=archive_path.parent, filter="data")
        archive_path.unlink()
        return archive_path, True, f"Extracted: {archive_path.name}"
    except Exception as e:
        return archive_path, False, f"Extract failed: {archive_path.name} - {e}"


def main():
    cwd = Path.cwd()
    archives = list(cwd.glob("*.tar.gz")) + list(cwd.glob("*.tar.xz")) + list(cwd.glob("*.tar.zst"))
    if not archives:
        print("No tar archives found in current directory")
        return
    print(f"Found {len(archives)} archive(s)\n--- Checking integrity ---")
    valid_archives = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(check_integrity, archive): archive for archive in archives}
        for future in as_completed(futures):
            is_valid, message = future.result()
            print(message)
            if is_valid:
                valid_archives.append(futures[future])
    if not valid_archives:
        print("\nNo valid archives to extract")
        return
    print(f"\n--- Extracting {len(valid_archives)} valid archive(s) ---")
    failed = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(extract_archive, archive): archive for archive in valid_archives}
        for future in as_completed(futures):
            path, success, message = future.result()
            print(message)
            if not success:
                failed.append(path)
    if failed:
        print(f"\n{len(failed)} extraction(s) failed")
        sys.exit(1)
    else:
        print(f"\nSuccessfully extracted {len(valid_archives)} archive(s)")


if __name__ == "__main__":
    raise SystemExit(main())
