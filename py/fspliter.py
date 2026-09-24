from __future__ import annotations

import argparse
import logging
import os
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
DEFAULT_MIN_CHARS = 4900
DEFAULT_MAX_CHARS = 4990
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".rst",
    ".log",
    ".csv",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".py",
    ".js",
    ".css",
    ".yml",
    ".yaml",
    ".cfg",
    ".ini",
}


def find_text_files(input_paths: list[Path], recursive: bool = True) -> list[Path]:
    text_files = []
    for path in input_paths:
        if not path.exists():
            logger.warning(f"Path does not exist: {path}")
            continue
        if path.is_file():
            if path.suffix.lower() in TEXT_EXTENSIONS or path.suffix.lower() == "":
                text_files.append(path)
            else:
                logger.warning(f"Skipping non-text file: {path}")
        elif path.is_dir():
            if recursive:
                for ext in TEXT_EXTENSIONS:
                    text_files.extend(path.rglob(f"*{ext}"))
                text_files.extend([f for f in path.rglob("*") if f.is_file() and f.suffix == ""])
            else:
                for ext in TEXT_EXTENSIONS:
                    text_files.extend(path.glob(f"*{ext}"))
                text_files.extend([f for f in path.glob("*") if f.is_file() and f.suffix == ""])
    seen = set()
    unique_files = []
    for f in text_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    return unique_files


def find_split_point(text: str, start_pos: int, min_chars: int, max_chars: int) -> int:
    end_pos = start_pos + max_chars
    if end_pos >= len(text):
        return len(text)
    search_start = start_pos + min_chars
    search_end = min(end_pos, len(text))
    search_text = text[search_start:search_end]
    sentence_pattern = re.compile(r"[.!?]\s+")
    matches = list(sentence_pattern.finditer(search_text))
    if matches:
        last_match = matches[-1]
        split_point = search_start + last_match.end()
        return split_point
    word_pattern = re.compile(r"\s+")
    matches = list(word_pattern.finditer(search_text))
    if matches:
        last_match = matches[-1]
        split_point = search_start + last_match.end()
        return split_point
    return end_pos


def split_text(text: str, min_chars: int, max_chars: int) -> list[str]:
    parts = []
    current_pos = 0
    while current_pos < len(text):
        split_point = find_split_point(text, current_pos, min_chars, max_chars)
        part = text[current_pos:split_point]
        part = part.rstrip()
        if part:
            parts.append(part)
        current_pos = split_point
    return parts


def process_file(input_file: Path, output_dir: Path, min_chars: int, max_chars: int) -> tuple[Path, int]:
    try:
        try:
            with open(input_file, encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(input_file, encoding="latin-1") as f:
                content = f.read()
        if not content.strip():
            logger.info(f"Skipping empty file: {input_file}")
            return (input_file, 0)
        parts = split_text(content, min_chars, max_chars)
        if not parts:
            logger.info(f"No parts generated for: {input_file}")
            return (input_file, 0)
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = input_file.stem
        suffix = input_file.suffix
        for i, part in enumerate(parts, 1):
            output_file = output_dir / f"{stem}_{i:03d}{suffix}"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(part)
        logger.info(f"Split {input_file.name} into {len(parts)} parts")
        return (input_file, len(parts))
    except Exception as e:
        logger.error(f"Error processing {input_file}: {e}")
        return (input_file, 0)


def process_file_wrapper(args):
    return process_file(*args)


def main():
    parser = argparse.ArgumentParser(
        description="Split text files into parts of 4900-4990 characters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s file1.txt file2.txt -o output/
  %(prog)s dir1/ dir2/ -o output/
  %(prog)s -o output/  (process all files in current directory)
  %(prog)s *.txt -o output/
  %(prog)s file.txt -o output/ --max-workers 4
        """,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Input files and/or directories to process. If not provided, processes current directory recursively.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("split_output"),
        help="Output directory for split files (default: split_output)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=os.cpu_count(),
        help=f"Maximum number of parallel workers (default: {os.cpu_count()})",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not search directories recursively",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=DEFAULT_MIN_CHARS,
        help=f"Minimum characters per part (default: {DEFAULT_MIN_CHARS})",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help=f"Maximum characters per part (default: {DEFAULT_MAX_CHARS})",
    )
    args = parser.parse_args()
    if args.inputs:
        input_paths = [Path(p) for p in args.inputs]
    else:
        input_paths = [Path(".")]
    text_files = find_text_files(input_paths, recursive=not args.no_recursive)
    if not text_files:
        logger.error("No text files found to process")
        return
    logger.info(f"Found {len(text_files)} file(s) to process")
    logger.info(f"Character limits: {args.min_chars}-{args.max_chars} per part")
    process_args = [(file_path, args.output, args.min_chars, args.max_chars) for file_path in text_files]
    total_parts = 0
    processed_files = 0
    with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        future_to_file = {executor.submit(process_file_wrapper, arg): arg[0] for arg in process_args}
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                _result_file, num_parts = future.result()
                total_parts += num_parts
                processed_files += 1
            except Exception as e:
                logger.error(f"Failed to process {file_path}: {e}")
    logger.info(f"Processing complete: {processed_files} files split into {total_parts} parts")
    logger.info(f"Output directory: {args.output.absolute()}")


if __name__ == "__main__":
    raise SystemExit(main())
