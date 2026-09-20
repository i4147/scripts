from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm


def find_png_files(directory: Path):
    png_files = []
    for root, _, files in os.walk(directory):
        png_files.extend(os.path.join(root, file) for file in files if file.lower().endswith(".png"))
    return png_files


def optimize_png(file_path):
    try:
        subprocess.run(["optipng", "-o7", str(file_path)], check=True)
        return True, file_path
    except subprocess.CalledProcessError as e:
        return False, file_path, str(e)


def main() -> None:
    cwd = Path.cwd()
    png_files = find_png_files(cwd)
    if not png_files:
        print("No PNG files found in the current directory.")
        return
    print(f"Found {len(png_files)} PNG files to optimize.")
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(optimize_png, file): file for file in png_files}
        results = []
        with tqdm(total=len(png_files), desc="Optimizing PNGs", unit="file") as pbar:
            for future in as_completed(futures):
                results.append(future.result())
                pbar.update(1)
    success = sum(1 for r in results if r[0])
    print(f"\nOptimization complete. Success: {success}/{len(png_files)} files.")


if __name__ == "__main__":
    raise SystemExit(main())
