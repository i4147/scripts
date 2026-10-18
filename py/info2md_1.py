import re
import sys
from multiprocessing import Pool
from pathlib import Path
from subprocess import run
from loguru import logger

WORKERS = 8
INFO_SUFFIX_PATTERN = re.compile(r"\.info(-\d+)?$")


def convert_info_file(info_path):
    stem = info_path.name
    base_name = INFO_SUFFIX_PATTERN.sub("", stem)
    md_path = info_path.parent / f"{base_name}.md"
    if md_path.exists():
        index = 1
        while (info_path.parent / f"{base_name}_{index}.md").exists():
            index += 1
        md_path = info_path.parent / f"{base_name}_{index}.md"
    result = run(
        ["info", str(info_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        md_path.write_text(result.stdout)
        info_path.unlink()
        print(f"Converted {info_path.name} -> {md_path.name}")
    else:
        logger.error(f"Failed to convert {info_path.name} (exit {result.returncode}): {result.stderr.strip()}")


def main():
    cwd = Path.cwd()
    info_files = list(cwd.glob("*.info*"))
    if not info_files:
        print("No .info files found.")
        return 0
    print(f"Converting {len(info_files)} .info file(s) with {WORKERS} workers.")
    with Pool(processes=WORKERS) as pool:
        async_results = [pool.apply_async(convert_info_file, (info_path,)) for info_path in info_files]
        for async_result in async_results:
            try:
                async_result.get()
            except Exception as exc:
                logger.exception(f"Worker raised an exception: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
