import os
import pathlib
import sys


def human_readable_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while size_bytes >= 1024 and i < len(units) - 1:
        size_bytes /= 1024
        i += 1
    return f"{size_bytes:.1f}{units[i]}"


def get_folder_size(path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, onerror=None):
        for f in files:
            try:
                fp = os.path.join(root, f)
                total += pathlib.Path(fp).stat().st_size
            except (
                FileNotFoundError,
                PermissionError,
            ):
                pass
    return total


def process_entry(entry):
    directory, name = entry
    full_path = os.path.join(directory, name)
    try:
        if pathlib.Path(full_path).is_dir():
            size_bytes = get_folder_size(full_path)
        else:
            size_bytes = pathlib.Path(full_path).stat().st_size
        return (
            size_bytes,
            name,
            human_readable_size(size_bytes),
        )
    except Exception:
        return (0, name, "ERR")


def list_files_sorted_and_formatted(
    directory: str = ".",
) -> None:
    try:
        names = [n for n in os.listdir(directory) if n not in {".", ".."}]
    except FileNotFoundError:
        return
    tasks = [(directory, name) for name in names]
    with mp.Pool(mp.cpu_count()) as pool:
        file_data = pool.map(process_entry, tasks)
    file_data.sort(key=operator.itemgetter(0))
    for _, _name, _human_size in file_data:
        pass


if __name__ == "__main__":
    target_directory = sys.argv[1] if len(sys.argv) > 1 else "."
    list_files_sorted_and_formatted(target_directory)
