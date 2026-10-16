from tree_sitter import Node
import ast
import logging
import os
import sys
from pathlib import Path
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)
PRESERVE_PREFIXES = ("# fmt:", "#!")


def get_directory_size(path: str) -> int:
    total_size = 0
    for dirpath, _, filenames in os.walk(path):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if not Path(filepath).is_symlink():
                try:
                    total_size += Path(filepath).stat().st_size
                except OSError as e:
                    logger.error(f"Error getting size of {filepath}: {e}")
    return total_size


def is_python_file(filepath: Path) -> bool:
    if filepath.suffix == ".py":
        return True
    if filepath.suffix == "":
        try:
            with Path(filepath).open("rb") as f:
                first_line = f.readline()
                if first_line.startswith(b"#!") and b"python" in first_line:
                    return True
        except (OSError, UnicodeDecodeError):
            pass
    return False


def should_preserve_comment(comment_text: str) -> bool:
    stripped = comment_text.strip()
    return any((stripped.startswith(prefix) for prefix in PRESERVE_PREFIXES))


def remove_comments_from_source(source_code: str) -> tuple[str, bool]:
    tree = parser.parse(bytes(source_code, "utf8"))
    root_node = tree.root_node
    comments_to_remove = []

    def traverse(node: Node) -> None:
        if node.type == "comment":
            comment_text = source_code[node.start_byte : node.end_byte]
            if not should_preserve_comment(comment_text):
                comments_to_remove.append((node.start_byte, node.end_byte))
        for child in node.children:
            traverse(child)

    traverse(root_node)
    if not comments_to_remove:
        return (source_code, False)
    comments_to_remove.sort(reverse=True)
    lines = source_code.split("\n")
    source_code.encode("utf8")
    for start_byte, end_byte in comments_to_remove:
        start_line = source_code[:start_byte].count("\n")
        end_line = source_code[:end_byte].count("\n")
        if start_line == end_line:
            line_start = source_code.rfind("\n", 0, start_byte) + 1
            start_col = start_byte - line_start
            end_byte - line_start
            line = lines[start_line]
            before_comment = line[:start_col].strip()
            if before_comment:
                lines[start_line] = line[:start_col].rstrip()
            else:
                lines[start_line] = ""
        else:
            for i in range(start_line, end_line + 1):
                lines[i] = ""
    result_lines = []
    for line in lines:
        if line or result_lines:
            result_lines.append(line)
    while result_lines and (not result_lines[-1]):
        result_lines.pop()
    modified_code = "\n".join(result_lines)
    if modified_code and (not modified_code.endswith("\n")):
        modified_code += "\n"
    return (modified_code, True)


def _cleanup_blank_lines(text: str) -> str:
    lines = text.splitlines()
    cleaned = []
    blank_streak = 0
    for line in lines:
        if line.strip() == "":
            blank_streak += 1
            if blank_streak <= 2:
                cleaned.append("")
        else:
            blank_streak = 0
            cleaned.append(line.rstrip())
    return "\n".join(cleaned) + "\n"


def validate_syntax(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError as e:
        logger.error(f"Syntax error: {e}")
        return False


def process_file(filepath: Path) -> bool:
    for part in filepath.parts:
        if "pip" in str(part):
            return False
    try:
        original_code = Path(filepath).read_text(encoding="utf-8")
        modified_code, was_modified = remove_comments_from_source(original_code)
        if not was_modified:
            return False
        modified_code = _cleanup_blank_lines(modified_code)
        if not validate_syntax(modified_code):
            logger.error(f"Syntax validation failed for {filepath}, skipping update")
            return False
        Path(filepath).write_text(modified_code, encoding="utf-8")
        logger.info(f"Processed: {filepath}")
        return True
    except Exception as e:
        logger.error(f"Error processing {filepath}: {e}")
        return False


def process_files(file_paths: list[Path]) -> tuple[int, int, int, int]:
    processed_count = 0
    modified_count = 0
    initial_total_size = 0
    final_total_size = 0
    for filepath in file_paths:
        if not filepath.exists():
            logger.error(f"File not found: {filepath}")
            continue
        if filepath.is_symlink():
            logger.warning(f"Skipping symlink: {filepath}")
            continue
        if not is_python_file(filepath):
            logger.warning(f"Skipping non-Python file: {filepath}")
            continue
        try:
            initial_size = filepath.stat().st_size
        except OSError as e:
            logger.error(f"Error getting size of {filepath}: {e}")
            continue
        processed_count += 1
        if process_file(filepath):
            modified_count += 1
            try:
                final_size = filepath.stat().st_size
                initial_total_size += initial_size
                final_total_size += final_size
            except OSError as e:
                logger.error(f"Error getting size of {filepath}: {e}")
    return (processed_count, modified_count, initial_total_size, final_total_size)


def process_directory(directory: Path) -> tuple[int, int, int, int]:
    initial_total_size = get_directory_size(str(directory))
    processed_count = 0
    modified_count = 0
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not Path(os.path.join(root, d)).is_symlink()]
        for filename in files:
            filepath = Path(root) / filename
            if filepath.is_symlink():
                continue
            if not is_python_file(filepath):
                continue
            processed_count += 1
            if process_file(filepath):
                modified_count += 1
    final_total_size = get_directory_size(str(directory))
    return (processed_count, modified_count, initial_total_size, final_total_size)


def print_summary(processed_count: int, modified_count: int, initial_size: int, final_size: int) -> None:
    size_reduction = initial_size - final_size
    reduction_percent = size_reduction / initial_size * 100 if initial_size > 0 else 0
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Files processed: {processed_count}")
    logger.info(f"Files modified: {modified_count}")
    logger.info(f"Initial size: {initial_size:,} bytes")
    logger.info(f"Final size: {final_size:,} bytes")
    logger.info(f"Size reduction: {size_reduction:,} bytes ({reduction_percent:.2f}%)")
    logger.info(f"{'=' * 60}")


def main() -> None:
    args = sys.argv[1:]
    if args:
        file_paths = [Path(arg) for arg in args]
        processed, modified, initial_size, final_size = process_files(file_paths)
        print_summary(processed, modified, initial_size, final_size)
    else:
        current_dir = Path.cwd()
        logger.info(f"Processing {current_dir} ...")
        processed, modified, initial_size, final_size = process_directory(current_dir)
        print_summary(processed, modified, initial_size, final_size)


if __name__ == "__main__":
    main()
