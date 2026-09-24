from __future__ import annotations

import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

COMMENT_PATTERN = re.compile("<!--.*?-->", re.DOTALL)


def remove_comments_from_file(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        new_content = COMMENT_PATTERN.sub("", content)
        if new_content != content:
            with open(path, "w", encoding="utf-8", errors="ignore") as f:
                f.write(new_content)
            return (path, True, None)
        else:
            return (path, False, None)
    except Exception as e:
        return (path, False, str(e))


def find_files(directory, extensions=None):
    if extensions is None:
        extensions = {".html", ".htm", ".css"}
    directory = Path(directory)
    if not directory.exists():
        raise ValueError(f"Directory {directory} does not exist")
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            yield path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Remove HTML comments from HTML and CSS files recursively.")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to process (default: current directory)",
    )
    parser.add_argument(
        "-e",
        "--extensions",
        nargs="+",
        default=[".html", ".htm", ".css"],
        help="File extensions to process (default: .html .htm .css)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: CPU count)",
    )
    args = parser.parse_args()
    extensions = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in args.extensions}
    try:
        files = list(find_files(args.directory, extensions))
        if not files:
            print(f"No files found with extensions: {', '.join(extensions)}")
            return
        print(f"Found {len(files)} files to process")
        print(f"Using {args.workers or os.cpu_count()} workers")
        print("-" * 40)
        updated_count = 0
        error_count = 0
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            future_to_file = {executor.submit(remove_comments_from_file, path): path for path in files}
            for future in as_completed(future_to_file):
                path, was_updated, error = future.result()
                rel_path = path.relative_to(args.directory)
                if error:
                    print(f"❌ ERROR: {rel_path} - {error}")
                    error_count += 1
                elif was_updated:
                    print(f"✓ UPDATED: {rel_path}")
                    updated_count += 1
        print("-" * 40)
        print("Summary:")
        print(f"  Total files processed: {len(files)}")
        print(f"  Files updated: {updated_count}")
        print(f"  Errors: {error_count}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
