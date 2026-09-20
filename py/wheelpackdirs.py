from __future__ import annotations

import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path


def pack_wheel(directory):
    try:
        subprocess.run(
            ["wheel", "pack", str(directory)],
            capture_output=True,
            text=True,
            check=True,
        )
        return True, f"✓ {directory.name}"
    except subprocess.CalledProcessError as e:
        return False, f"✗ {directory.name}: {e.stderr.strip()}"


def main():
    parser = argparse.ArgumentParser(description="Pack wheel directories in parallel")
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=cpu_count(),
        help=f"Number of parallel jobs (default: {cpu_count()})",
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Directory containing wheel dirs (default: current)",
    )
    args = parser.parse_args()
    directories = [d for d in args.directory.iterdir() if d.is_dir()]
    if not directories:
        print("No directories found")
        return
    print(f"Processing {len(directories)} directories using {args.jobs} workers")
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(pack_wheel, directory): directory for directory in directories}
        success_count = 0
        fail_count = 0
        for future in as_completed(futures):
            directory = futures[future]
            try:
                success, message = future.result()
                print(message)
                if success:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                print(f"✗ {directory.name}: Exception - {e}")
                fail_count += 1
    print(f"\nDone: {success_count} successful, {fail_count} failed")


if __name__ == "__main__":
    raise SystemExit(main())
