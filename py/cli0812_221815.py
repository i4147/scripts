import argparse
import json
import mmap
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path

MMAP_THRESHOLD = 5 * 1024 * 1024


def process_json_file(args_tuple):

    file_path, minify, sort_keys = args_tuple
    file_path = Path(file_path)

    try:
        file_size = file_path.stat().st_size

        if file_size > MMAP_THRESHOLD:
            with open(file_path, "r+b") as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mmapped_file:
                    content = mmapped_file.read().decode("utf-8")
                    data = json.loads(content)
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

        indent = None if minify else 2

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, sort_keys=sort_keys, ensure_ascii=False)

        return (str(file_path), True, None)

    except json.JSONDecodeError as e:
        return (str(file_path), False, f"Invalid JSON: {e}")
    except Exception as e:
        return (str(file_path), False, f"Error: {e}")


def collect_json_files(paths, recursive=True):

    json_files = set()

    for path in paths:
        path = Path(path)

        if path.is_file():
            if path.suffix.lower() == ".json":
                json_files.add(path)
        elif path.is_dir():
            if recursive:
                pattern = "**/*.json"
                json_files.update(path.glob(pattern))
            else:
                json_files.update(path.glob("*.json"))

    return json_files


def main():

    parser = argparse.ArgumentParser(
        description="Prettify or minify JSON files with multiprocessing support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  jb                    
  jb file.json         
  jb -m file.json      
  jb -s dir/           
  jb -m -s file.json   
  jb file1.json dir1/  
        """,
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-b", "--beautify", action="store_true", default=True, help="Beautify/prettify JSON (default)"
    )
    mode_group.add_argument("-m", "--minify", action="store_true", help="Minify JSON (remove whitespace)")

    parser.add_argument(
        "-s", "--sort-keys", action="store_true", default=False, help="Sort JSON keys alphabetically (default: False)"
    )

    parser.add_argument(
        "paths", nargs="*", default=None, help="JSON files or directories to process (default: current directory)"
    )

    parser.add_argument(
        "--workers", type=int, default=None, help=f"Number of worker processes (default: CPU count = {cpu_count()})"
    )

    args = parser.parse_args()

    if not args.paths:
        args.paths = ["."]

    minify = args.minify

    json_files = collect_json_files(args.paths, recursive=True)

    if not json_files:
        print("No JSON files found.", file=sys.stderr)
        sys.exit(1)

    process_args = [(f, minify, args.sort_keys) for f in sorted(json_files)]

    workers = args.workers or cpu_count()
    workers = min(workers, len(process_args))

    print(f"Processing {len(json_files)} JSON file(s) using {workers} worker(s)...")
    mode_text = "Minifying" if minify else "Prettifying"
    sort_text = " with sorted keys" if args.sort_keys else ""
    print(f"{mode_text}{sort_text}...")

    with Pool(processes=workers) as pool:
        results = pool.map(process_json_file, process_args)

    success_count = 0
    error_count = 0

    for file_path, success, error in results:
        if success:
            success_count += 1
        else:
            error_count += 1
            print(f"✗ {file_path}: {error}", file=sys.stderr)

    print(f"\n✓ Successfully processed: {success_count} file(s)")
    if error_count > 0:
        print(f"✗ Failed: {error_count} file(s)")
        sys.exit(1)
    else:
        print("All files processed successfully!")


if __name__ == "__main__":
    main()
