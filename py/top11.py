import operator
import sys
from pathlib import Path


def get_file_sizes(start_path: str = "."):
    file_sizes = []
    start_path = Path(start_path).resolve()
    try:
        for file_path in start_path.rglob("*"):
            if file_path.is_file():
                try:
                    file_size = file_path.stat().st_size
                    relative_path = file_path.relative_to(start_path)
                    file_sizes.append((relative_path, file_size))
                except (OSError, ValueError):
                    continue
    except PermissionError as e:
        print(
            f"Permission denied: {e}",
            file=sys.stderr,
        )
        return []
    return file_sizes


def format_size(size_bytes) -> str:
    if size_bytes == 0:
        return "0 B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.2f} {size_names[i]}"


def main() -> None:
    print("Scanning files...")
    file_sizes = get_file_sizes()
    if not file_sizes:
        print("No files found or unable to access directory.")
        return
    file_sizes.sort(key=operator.itemgetter(1), reverse=True)
    top_files = file_sizes[:10]
    print("\n" + "=" * 60)
    print(f"TOP 10 LARGEST FILES (in {Path.cwd()})")
    print("=" * 60)
    if not top_files:
        print("No files found.")
        return
    max_path_len = max(len(str(path)) for path, size in top_files)
    max_path_len = min(max_path_len, 80)
    print(f"{'No.':<4} {'File Path':<{max_path_len}} {'Size':>12}")
    print("-" * (max_path_len + 20))
    for i, (file_path, size) in enumerate(top_files, 1):
        path_str = str(file_path)
        if len(path_str) > max_path_len:
            path_str = "..." + path_str[-(max_path_len - 3) :]
        size_str = format_size(size)
        print(f"{i:<4} {path_str:<{max_path_len}} {size_str:>12}")
    total_files = len(file_sizes)
    print("-" * (max_path_len + 20))
    print(f"Total files scanned: {total_files}")
    if total_files > 10:
        print(f"Showing top 10 out of {total_files} files")


def alternative_version_with_details() -> None:
    file_sizes = get_file_sizes()
    if not file_sizes:
        print("No files found.")
        return
    file_sizes.sort(key=operator.itemgetter(1), reverse=True)
    top_files = file_sizes[:10]
    print("\nTOP 10 LARGEST FILES (Detailed View)")
    print("=" * 70)
    for i, (file_path, size) in enumerate(top_files, 1):
        size_str = format_size(size)
        print(f"{i:2d}. {size_str:>10} - {file_path}")


if __name__ == "__main__":
    try:
        alternative_version_with_details()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(
            f"An error occurred: {e}",
            file=sys.stderr,
        )
        sys.exit(1)
