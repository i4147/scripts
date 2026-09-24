import subprocess
from multiprocessing import Pool
from pathlib import Path
from typing import Final
from loguru import logger
from tqdm import tqdm

MAX_WORKERS = 8
PNG_SUFFIX = ".png"


def find_png_files(directory):
    return [p for p in directory.rglob("*") if p.suffix.lower() == PNG_SUFFIX]


def optimize_png(path):
    try:
        subprocess.run(
            ["optipng", "-o7", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        return False, path, str(exc)
    else:
        return True, path, None


def main():
    cwd = Path.cwd()
    png_files = find_png_files(cwd)
    if not png_files:
        logger.warning("No PNG files found in the current directory.")
        return 0
    print(f"Found {len(png_files)} PNG files to optimize.")
    results = []
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(optimize_png, (file,)) for file in png_files]
        with tqdm(total=len(png_files), desc="Optimizing PNGs", unit="file") as pbar:
            for async_result in async_results:
                results.append(async_result.get())
                pbar.update(1)
    success = sum(1 for ok, _, _ in results if ok)
    print(f"Optimization complete. Success: {success}/{len(png_files)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
