
import argparse
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple

from tree_sitter import Language, Parser
import tree_sitter_bash as ts_bash



def get_parser() -> Parser:
    BASH_LANGUAGE = Language(ts_bash.language())
    parser = Parser()
    parser.set_language(BASH_LANGUAGE)
    return parser


def remove_comments_from_content(content: str) -> Tuple[str, int]:
    parser = get_parser()
    tree = parser.parse(bytes(content, "utf-8"))
    root = tree.root_node

    
    comment_nodes = []
    comment_types = {"comment", "shebang"}

    def collect_comments(node):
        if node.type in comment_types:
            comment_nodes.append(node)
        for child in node.children:
            collect_comments(child)

    collect_comments(root)

    if not comment_nodes:
        return content, 0

    
    lines = content.splitlines(keepends=True)
    comment_count = 0
    cleaned_lines = []

    
    comment_nodes.sort(key=lambda n: (n.start_point[0], n.start_point[1]))

    
    keep_line = [True] * len(lines)

    for node in comment_nodes:
        start_line = node.start_point[0]
        end_line = node.end_point[0]

        
        if start_line == end_line:
            start_col = node.start_point[1]
            end_col = node.end_point[1]

            
            line_start = lines[start_line][:start_col].strip()
            if not line_start or line_start == "#" or line_start.startswith("#"):
                
                keep_line[start_line] = False
                comment_count += 1
            else:
                
                line = lines[start_line]
                
                if line.rstrip().endswith(("#" + node.text.decode("utf-8").lstrip("#"))):
                    
                    
                    before_comment = line[:start_col].rstrip()
                    if line.endswith("\n"):
                        cleaned_lines.append(before_comment + "\n")
                    else:
                        cleaned_lines.append(before_comment)
                    comment_count += 1
                    keep_line[start_line] = False  
                else:
                    
                    cleaned_lines.append(line)
        else:
            
            for line_idx in range(start_line, end_line + 1):
                if line_idx < len(keep_line):
                    keep_line[line_idx] = False
            comment_count += 1

    
    result_lines = []
    for idx, line in enumerate(lines):
        if keep_line[idx]:
            
            if not any(
                c.start_point[0] == idx and c.start_point[1] < len(line)
                for c in comment_nodes
                if c.start_point[0] == idx
            ):
                result_lines.append(line)
            else:
                
                
                pass

    
    
    if any(
        c.start_point[0] == c.end_point[0]
        and any(c.start_point[1] > 0 for c in comment_nodes if c.start_point[0] == c.end_point[0])
    ):
        
        final_lines = []
        for line_num, line in enumerate(lines):
            
            inline_comments = [
                c for c in comment_nodes if c.start_point[0] == c.end_point[0] == line_num and c.start_point[1] > 0
            ]
            if inline_comments:
                
                comment = inline_comments[0]
                before_comment = line[: comment.start_point[1]].rstrip()
                if line.endswith("\n"):
                    final_lines.append(before_comment + "\n")
                else:
                    final_lines.append(before_comment)
                comment_count += len(inline_comments)
            elif keep_line[line_num]:
                final_lines.append(line)
        result_lines = final_lines

    
    if not result_lines:
        result_lines = []
        for idx, line in enumerate(lines):
            if keep_line[idx] or idx < len(lines):
                result_lines.append(line)

    return "".join(result_lines), comment_count


def process_file(file_path: Path) -> Tuple[Path, int, bool]:
    try:
        content = file_path.read_text(encoding="utf-8")
        cleaned_content, comment_count = remove_comments_from_content(content)

        if comment_count > 0:
            file_path.write_text(cleaned_content, encoding="utf-8")

        return file_path, comment_count, True
    except Exception as e:
        logging.error(f"Error processing {file_path}: {e}")
        return file_path, 0, False


def is_bash_file(path: Path) -> bool:
    
    if path.suffix in {".sh", ".bash", ".zsh", ".ksh"}:
        return True

    
    try:
        with open(path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line.startswith("#!") and "bash" in first_line.lower():
                return True
    except (UnicodeDecodeError, IOError):
        pass

    return False


def collect_files(paths: List[Path], recursive: bool = True) -> List[Path]:
    files = []

    for path in paths:
        if not path.exists():
            logging.warning(f"Path does not exist: {path}")
            continue

        if path.is_file():
            if is_bash_file(path):
                files.append(path)
        elif path.is_dir():
            if recursive:
                for file_path in path.rglob("*"):
                    if file_path.is_file() and is_bash_file(file_path):
                        files.append(file_path)
            else:
                for file_path in path.glob("*"):
                    if file_path.is_file() and is_bash_file(file_path):
                        files.append(file_path)

    return files


def main():
    parser = argparse.ArgumentParser(description="Remove comments from bash files recursively")
    parser.add_argument(
        "inputs", nargs="*", type=Path, help="Files or directories to process (default: current directory)"
    )
    parser.add_argument("--no-recursive", action="store_true", help="Don't process subdirectories recursively")
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel workers (default: CPU count)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed without making changes")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")

    args = parser.parse_args()

    
    log_level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(message)s")

    
    if not args.inputs:
        inputs = [Path.cwd()]
    else:
        inputs = args.inputs

    
    files = collect_files(inputs, recursive=not args.no_recursive)

    if not files:
        print("No bash files found to process.")
        return 0

    print(f"Found {len(files)} bash files to process")

    if args.dry_run:
        print("\nFiles that would be processed:")
        for f in files:
            print(f"  {f}")
        return 0

    
    total_comments = 0
    processed = 0
    failed = 0
    results = []

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_file, f): f for f in files}

        for future in as_completed(futures):
            file_path, comment_count, success = future.result()
            processed += 1
            if success:
                total_comments += comment_count
                if comment_count > 0 and args.verbose:
                    print(f"✓ {file_path}: removed {comment_count} comments")
                elif args.verbose:
                    print(f"  {file_path}: no comments found")
            else:
                failed += 1

    
    print(f"\n{'=' * 50}")
    print(f"Summary:")
    print(f"  Files processed: {processed}")
    print(f"  Files failed: {failed}")
    print(f"  Total comments removed: {total_comments}")

    if failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
