import multiprocessing as mp
import os
import subprocess

FILE_EXTENSIONS = {".c", ".cpp", ".cxx", ".cc", ".h", ".hh", ".hpp", ".hxx"}


def format_file(file_path):
    try:
        subprocess.run(["clang-format", "-i", file_path], check=True)
        return file_path
    except subprocess.CalledProcessError:
        return None


def find_files():
    all_files = []
    for root, _, files in os.walk("."):
        all_files.extend(
            os.path.join(root, file) for file in files if any(file.endswith(ext) for ext in FILE_EXTENSIONS)
        )
    return all_files


def format_files_parallel(files):
    with mp.Pool(8) as pool:
        return list(pool.map(format_file, files))


def main() -> None:
    files_to_format = find_files()
    if not files_to_format:
        print("No files found with the specified extensions.")
        return
    formatted_files = format_files_parallel(files_to_format)
    formatted_files = [file for file in formatted_files if file is not None]
    print(f"\nFormatted {len(formatted_files)} files.")


if __name__ == "__main__":
    main()
