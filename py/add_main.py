import os
import sys
from pathlib import Path
from dh import fsz, get_files, gsz

MAINBLOCK_INDICATOR = 'if __name__ == "__main__":'
MAX_QUEUE = 16


def add_main_block_if_missing(filepath: Path) -> None:
    if filepath.is_symlink() or not filepath.is_file():
        return
    try:
        original_content = filepath.read_text(encoding="utf-8")
        content_lines = original_content.splitlines()
        if MAINBLOCK_INDICATOR in original_content:
            return
        print(f"Adding __main__ block to: '{filepath.name}'")
        lines_to_add = ["", MAINBLOCK_INDICATOR, "    # Placeholder for main execution logic", "    pass", ""]
        new_content_lines = content_lines[:]
        if new_content_lines and not new_content_lines[-1].endswith("\n"):
            new_content_lines.append("")
        new_content_lines.extend(lines_to_add)
        new_content = "\n".join(new_content_lines)
        Path(filepath).write_text(new_content, encoding="utf-8")
    except UnicodeDecodeError:
        print(f"Skipping '{filepath.name}' due to encoding issues (expected UTF-8).")
    except OSError as e:
        print(f"Error processing '{filepath.name}': {e}")
    except Exception as e:
        print(f"An unexpected error occurred with '{filepath.name}': {e}")


def main() -> None:
    cwd = Path.cwd()
    initial_directory_size = gsz(cwd)
    args = sys.argv[1:]
    files_to_process = []
    if args:
        for arg in args:
            path = Path(arg)
            if path.is_file() and path.suffix == ".py":
                files_to_process.append(path)
            elif path.is_dir():
                print(f"Searching for Python files in directory: {path}")
                files_to_process.extend(get_files(path, ext=[".py"]))
            else:
                print(f"Warning: '{arg}' is not a Python file or directory. Skipping.")
    else:
        print(f"No arguments provided. Searching for Python files in '{cwd}' and its subdirectories...")
        files_to_process = get_files(cwd, ext=[".py"])
    if not files_to_process:
        print("No Python files found to process.")
        sys.exit(0)
    if len(files_to_process) == 1:
        add_main_block_if_missing(files_to_process[0])
        sys.exit(0)
    try:
        from multiprocessing import get_context

        num_processes = min(len(files_to_process), os.cpu_count() or 4)
        print(f"Processing {len(files_to_process)} files using {num_processes} processes...")
        with get_context("spawn").Pool(num_processes) as pool:
            for _ in pool.imap_unordered(add_main_block_if_missing, files_to_process):
                pass
    except ImportError:
        print("Multiprocessing not available or failed to import. Falling back to sequential processing.")
        for f in files_to_process:
            add_main_block_if_missing(f)
    except Exception as e:
        print(f"An error occurred during multiprocessing: {e}. Falling back to sequential processing.")
        for f in files_to_process:
            add_main_block_if_missing(f)
    final_directory_size = gsz(cwd)
    space_saved = initial_directory_size - final_directory_size
    try:
        from dh import cprint

        cprint(f"Operation complete. Space saved: {fsz(space_saved)}", "cyan")
    except ImportError:
        print(f"Operation complete. Space saved: {fsz(space_saved)}")


if __name__ == "__main__":
    main()
