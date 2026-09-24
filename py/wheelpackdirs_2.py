import argparse
import subprocess
from multiprocessing import Pool
from pathlib import Path
from loguru import logger

POOL_SIZE = 8


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


def parse_args():
    parser = argparse.ArgumentParser(description="Pack wheel directories in parallel")
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Directory containing wheel dirs (default: current)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    directories = [d for d in args.directory.iterdir() if d.is_dir()]
    if not directories:
        logger.warning("No directories found")
        return 1
    print(
        "Processing {} directories using {} workers",
        len(directories),
        POOL_SIZE,
    )
    success_count = 0
    fail_count = 0
    with Pool(processes=POOL_SIZE) as pool:
        async_results = [(directory, pool.apply_async(pack_wheel, (directory,))) for directory in directories]
        for directory, async_result in async_results:
            try:
                success, message = async_result.get()
                print(message)
                if success:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                logger.error("✗ {}: Exception - {}", directory.name, e)
                fail_count += 1
    print("Done: {} successful, {} failed", success_count, fail_count)
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
