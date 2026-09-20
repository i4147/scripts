
import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


def is_text_file(filepath: Path) -> bool:
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(1024)
            return b"\0" not in chunk
    except OSError:
        return False


def extract_blocks(lines: List[str], start_line: int, min_lines: int = 2) -> List[Tuple[str, int, List[str]]]:
    blocks = []
    i = 0
    while i < len(lines):
        raw_line = lines[i]
        original = raw_line.rstrip("\n\r")
        stripped = original.strip()

        
        if stripped.startswith("#!"):
            i += 1
            continue

        
        block_start = i
        block_lines = []
        block_stripped = []
        while i < len(lines):
            raw_line = lines[i]
            original = raw_line.rstrip("\n\r")
            stripped = original.strip()

            if stripped.startswith("#!"):
                i += 1
                break

            block_lines.append(original)
            block_stripped.append(stripped)
            i += 1

        if len(block_stripped) >= min_lines:
            block_text = "\n".join(block_stripped)
            blocks.append((block_text, start_line + block_start, block_lines))
    return blocks


def collect_blocks(root: Path, min_lines: int = 2) -> Dict[str, List[Tuple[Path, int, List[str]]]]:
    blocks: Dict[str, List[Tuple[Path, int, List[str]]]] = defaultdict(list)
    for filepath in root.rglob("*"):
        if not filepath.is_file():
            continue
        if not is_text_file(filepath):
            continue
        try:
            with open(filepath, encoding="utf-8") as f:
                lines = f.readlines()
        except (OSError, UnicodeDecodeError) as e:
            print(f"Warning: cannot read {filepath}: {e}", file=sys.stderr)
            continue
        file_blocks = extract_blocks(lines, 1, min_lines)
        for block_text, start_lineno, original_lines in file_blocks:
            blocks[block_text].append((filepath, start_lineno, original_lines))
    return blocks


def find_repeated_blocks(
    blocks: Dict[str, List[Tuple[Path, int, List[str]]]],
) -> Dict[str, List[Tuple[Path, int, List[str]]]]:
    return {block: occ for block, occ in blocks.items() if len(occ) >= 2}


def report(repeated: Dict[str, List[Tuple[Path, int, List[str]]]], root: Path) -> None:
    if not repeated:
        print("No repeated multi-line blocks found.")
        return
    print(f"Found {len(repeated)} repeated multi-line block(s):")
    for i, (block_text, occurrences) in enumerate(repeated.items(), 1):
        line_count = block_text.count("\n") + 1
        print(f"\n--- Block {i} ({len(occurrences)} occurrences, {line_count} lines) ---")
        for line in block_text.split("\n"):
            print(f"  {line}")
        print("  Found in:")
        for filepath, lineno, _ in occurrences:
            rel_path = filepath.relative_to(root) if filepath.is_relative_to(root) else filepath
            print(f"    {rel_path}:{lineno}")


def remove_repeated_blocks(repeated: Dict[str, List[Tuple[Path, int, List[str]]]], root: Path) -> None:
    file_removals: Dict[Path, List[Tuple[int, List[str]]]] = defaultdict(list)
    for block_text, occurrences in repeated.items():
        for filepath, start_lineno, original_lines in occurrences:
            file_removals[filepath].append((start_lineno, original_lines))

    removed_total = 0
    files_changed = 0
    for filepath, removals in file_removals.items():
        try:
            with open(filepath, encoding="utf-8") as f:
                original_lines = f.readlines()
        except OSError as e:
            print(f"Warning: cannot read {filepath} for removal: {e}", file=sys.stderr)
            continue

        lines_to_remove = set()
        for start_lineno, block_lines in removals:
            for offset in range(len(block_lines)):
                lines_to_remove.add(start_lineno + offset - 1)  

        new_lines = []
        file_removed = 0
        for idx, raw_line in enumerate(original_lines):
            if idx in lines_to_remove:
                file_removed += 1
                continue
            new_lines.append(raw_line)

        if file_removed == 0:
            continue

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            removed_total += file_removed
            files_changed += 1
            rel_path = filepath.relative_to(root) if filepath.is_relative_to(root) else filepath
            print(f"Removed {file_removed} line(s) from {rel_path}")
        except Exception as e:
            print(f"Error: cannot write {filepath}: {e}", file=sys.stderr)

    if files_changed > 0:
        print(f"\nDone. Removed {removed_total} repeated line(s) from {files_changed} file(s).")
    else:
        print("No files were modified.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-r", "--remove", action="store_true", help="Remove found repeated multi-line blocks from files"
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=3,
        help="Minimum number of consecutive lines to consider a block (default: 2)",
    )
    args = parser.parse_args()
    root = Path.cwd()
    blocks = collect_blocks(root, args.min_lines)
    repeated = find_repeated_blocks(blocks)
    if args.remove:
        if not repeated:
            print("No repeated multi-line blocks to remove.")
        else:
            remove_repeated_blocks(repeated, root)
    else:
        report(repeated, root)


if __name__ == "__main__":
    main()
