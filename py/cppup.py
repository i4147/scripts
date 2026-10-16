from __future__ import annotations

import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter

import fastwalk

FILE_EXTENSIONS = {
    ".c",
    ".cpp",
    ".cxx",
    ".cc",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".C",
    ".CPP",
    ".CXX",
    ".CC",
    ".H",
    ".HH",
    ".HPP",
    ".HXX",
}


def format_file(file_path) -> bool:
    pth = Path(file_path)
    print(f"formating {pth.stem}")
    try:
        subprocess.run(["clang-format", "-i", file_path], check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def find_files():
    all_files = []
    for file in fastwalk.walk("."):
        path = Path(file)
        if path.is_file() and path.suffix in FILE_EXTENSIONS:
            all_files.append(path)
    return all_files


def main() -> None:
    start = perf_counter()
    files_to_format = find_files()
    if not files_to_format:
        print("No files found.")
        return
    print(f"Formatting {len(files_to_format)} files...")
    with ProcessPoolExecutor(max_workers=12) as executor:
        results = executor.map(format_file, files_to_format)
        sum(1 for success in results if success)
    print(f"{perf_counter() - start} sec")


if __name__ == "__main__":
    raise SystemExit(main())
