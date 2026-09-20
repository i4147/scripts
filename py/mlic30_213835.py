
import argparse
import concurrent.futures
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple
import sys

MIN_LINES = 2
MIN_CHARS = 10


def find_multiline_strings(
    file_path: Path, min_lines: int = 2, min_chars: int = 10
) -> Dict[str, List[Tuple[int, int]]]:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
        return {}
    strings = defaultdict(list)
    i = 0
    while i < len(lines):
        if lines[i].strip():
            start = i
            string_lines = [lines[i]]
            i += 1
            while i < len(lines) and lines[i].strip():
                string_lines.append(lines[i])
                i += 1
            end = i - 1
            full_string = "".join(string_lines)
            if len(string_lines) >= min_lines and len(full_string.strip()) >= min_chars:
                normalized = normalize_string(full_string)
                strings[normalized].append((start, end))
        else:
            i += 1
    return strings


def normalize_string(text: str) -> str:
    return "\n".join((line.rstrip() for line in text.splitlines()))


def find_files(directory: Path, extensions: Set[str] = None) -> List[Path]:
    if extensions is None:
        extensions = {
            ".txt",
            ".md",
            ".py",
            ".js",
            ".html",
            ".css",
            ".xml",
            ".json",
            ".yaml",
            ".yml",
            ".csv",
            ".log",
            ".ini",
            ".cfg",
            ".conf",
            ".sh",
            ".bat",
            ".ps1",
            ".java",
            ".cpp",
            ".c",
            ".h",
            ".rb",
            ".php",
            ".sql",
        }
    files = []
    try:
        for item in directory.rglob("*"):
            if item.is_file() and item.suffix.lower() in extensions:
                files.append(item)
    except PermissionError:
        print(f"Permission denied accessing {directory}", file=sys.stderr)
    return files


def process_file(args: Tuple[Path, int, int]) -> Tuple[Path, Dict[str, List[Tuple[int, int]]]]:
    file_path, min_lines, min_chars = args
    strings = find_multiline_strings(file_path, min_lines, min_chars)
    return (file_path, strings)


def find_repeated_strings(
    directory: Path, min_lines: int = 2, min_chars: int = 10, max_workers: int = None
) -> Dict[str, List[Tuple[Path, List[Tuple[int, int]]]]]:
    files = find_files(directory)
    if not files:
        print("No text files found in directory", file=sys.stderr)
        return {}
    print(f"Found {len(files)} files to process...")
    all_strings = defaultdict(list)
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        args = [(f, min_lines, min_chars) for f in files]
        futures = {executor.submit(process_file, arg): arg[0] for arg in args}
        for future in concurrent.futures.as_completed(futures):
            file_path = futures[future]
            try:
                file_path, strings = future.result()
                for norm_str, positions in strings.items():
                    all_strings[norm_str].append((file_path, positions))
            except Exception as e:
                print(f"Error processing {file_path}: {e}", file=sys.stderr)
    repeated = {k: v for k, v in all_strings.items() if len(v) > 1}
    return repeated


def remove_strings_from_files(
    repeated_strings: Dict[str, List[Tuple[Path, List[Tuple[int, int]]]]], string_numbers: List[int] = None
):
    files_to_modify = defaultdict(set)

    
    if string_numbers:
        selected_strings = {}
        for i, (norm_str, occurrences) in enumerate(repeated_strings.items(), 1):
            if i in string_numbers:
                selected_strings[norm_str] = occurrences
    else:
        selected_strings = repeated_strings

    for norm_str, occurrences in selected_strings.items():
        for file_path, positions in occurrences:
            files_to_modify[file_path].update(positions)

    for file_path, positions in files_to_modify.items():
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            sorted_positions = sorted(positions, key=lambda x: x[0], reverse=True)
            for start, end in sorted_positions:
                del lines[start : end + 1]
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            print(f"Removed {len(positions)} string(s) from {file_path}")
        except Exception as e:
            print(f"Error modifying {file_path}: {e}", file=sys.stderr)


def save_strings_to_file(repeated_strings: Dict[str, List[Tuple[Path, List[Tuple[int, int]]]]], output_file: Path):
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("Repeated Multiline Strings Report\n")
            f.write("=" * 50 + "\n\n")
            for i, (norm_str, occurrences) in enumerate(repeated_strings.items(), 1):
                f.write(f"String #{i} (found {len(occurrences)} times):\n")
                f.write("-" * 30 + "\n")
                f.write(norm_str)
                f.write("\n\n")
                f.write("Found in:\n")
                for file_path, positions in occurrences:
                    f.write(f"  - {file_path}\n")
                    for start, end in positions:
                        f.write(f"    Lines {start + 1}-{end + 1}\n")
                f.write("\n" + "=" * 50 + "\n\n")
        print(f"Report saved to {output_file}")
    except Exception as e:
        print(f"Error saving report: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Find repeated multiline strings in text files recursively")
    parser.add_argument("directory", nargs="?", default=".", help="Directory to search (default: current directory)")
    parser.add_argument(
        "-r",
        "--remove",
        nargs="*",
        type=int,
        help="Remove found repeated strings. Optionally specify string numbers (e.g., -r 2 4 to remove strings #2 and #4)",
    )
    parser.add_argument("-s", "--save", action="store_true", help="Save found strings to lic.txt in current directory")
    parser.add_argument(
        "--min-lines",
        type=int,
        default=MIN_LINES,
        help=f"Minimum number of lines for a multiline string (default: {MIN_LINES})",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=MIN_CHARS,
        help=f"Minimum number of characters for a multiline string (default: {MIN_CHARS})",
    )
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel workers (default: CPU count)")
    parser.add_argument("--extensions", nargs="+", help="File extensions to process (e.g., .txt .md .py)")
    args = parser.parse_args()
    directory = Path(args.directory)
    if not directory.exists():
        print(f"Directory {directory} does not exist", file=sys.stderr)
        sys.exit(1)
    print(f"Searching for repeated multiline strings in {directory}...")
    if args.extensions:
        extensions = set(args.extensions)
        global find_files
        original_find_files = find_files

        def find_files_with_ext(directory, _=None):
            return original_find_files(directory, extensions)

        find_files = find_files_with_ext
    repeated = find_repeated_strings(
        directory, min_lines=args.min_lines, min_chars=args.min_chars, max_workers=args.workers
    )
    if not repeated:
        print("No repeated multiline strings found.")
        return
    print(f"\nFound {len(repeated)} repeated multiline strings:")
    for i, (norm_str, occurrences) in enumerate(repeated.items(), 1):
        preview = norm_str[:100] + "..." if len(norm_str) > 100 else norm_str
        preview = preview.replace("\n", "\\n")
        print(f"\n{i}. Found in {len(occurrences)} files:")
        print(f"   Preview: {preview}")
        for file_path, positions in occurrences:
            print(f"   - {file_path}")
            for start, end in positions:
                print(f"     Lines {start + 1}-{end + 1}")
    if args.remove is not None:
        string_numbers = args.remove if args.remove else None
        if string_numbers:
            
            max_num = len(repeated)
            invalid_nums = [n for n in string_numbers if n < 1 or n > max_num]
            if invalid_nums:
                print(f"\nError: Invalid string numbers: {invalid_nums}. Valid range: 1-{max_num}", file=sys.stderr)
                sys.exit(1)
            print(f"\nRemoving strings: {string_numbers}...")
        else:
            print("\nRemoving all repeated strings from files...")
        remove_strings_from_files(repeated, string_numbers)
    if args.save:
        output_file = Path.cwd() / "lic.txt"
        print(f"\nSaving report to {output_file}...")
        save_strings_to_file(repeated, output_file)


if __name__ == "__main__":
    main()
