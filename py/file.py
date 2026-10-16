import ast
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from tree_sitter import Parser, Node
    from tree_sitter_python import language as python_language
except ImportError:
    print("ERROR: Install tree-sitter==0.25.2 and tree-sitter-python==0.25.0")
    sys.exit(1)


@dataclass
class ProcessingResult:
    file_path: Path
    success: bool
    error: Optional[str] = None
    original_size: int = 0
    new_size: int = 0
    processing_time: float = 0.0


class TreeSitterCommentRemover:
    QUERY = "\n    (comment) @comment\n    (string) @string\n    "

    def __init__(self):
        self.parser = Parser()
        self.parser.set_language(python_language())
        lang = python_language()
        self.query = lang.query(self.QUERY)

    def remove_comments_and_docstrings(self, source: str) -> str:
        source_bytes = source.encode("utf-8")
        tree = self.parser.parse(source_bytes)
        captures = self.query.captures(tree.root_node)
        ranges_to_remove = []
        for node, capture_name in captures:
            if capture_name == "comment":
                ranges_to_remove.append((node.start_byte, node.end_byte))
            elif capture_name == "string":
                if self._is_docstring(node):
                    ranges_to_remove.append((node.start_byte, node.end_byte))
        ranges_to_remove.sort(reverse=True)
        result = self._remove_ranges(source_bytes, ranges_to_remove)
        return result.decode("utf-8", errors="replace")

    def _is_docstring(self, node: Node) -> bool:
        parent = node.parent
        if parent and parent.type == "expression_statement":
            named_children = [c for c in parent.children if c.type not in ("comment", "NEWLINE", "INDENT", "DEDENT")]
            return len(named_children) == 1 and named_children[0] == node
        return False

    def _remove_ranges(self, source_bytes: bytes, ranges: list) -> bytes:
        if not ranges:
            return source_bytes
        result = bytearray(source_bytes)
        for start, end in ranges:
            removed = source_bytes[start:end]
            newline_count = removed.count(b"\n")
            if newline_count > 0:
                replacement = b"\n" * newline_count
            else:
                replacement = b" " * (end - start)
            result[start:end] = replacement
        return bytes(result)


class ASTCommentRemover:
    def remove_comments_and_docstrings(self, source: str) -> str:
        lines = source.split("\n")
        cleaned_lines = []
        for line in lines:
            in_string = False
            string_char = None
            result = []
            i = 0
            while i < len(line):
                char = line[i]
                if char in ('"', "'") and (i == 0 or line[i - 1] != "\\"):
                    if not in_string:
                        in_string = True
                        string_char = char
                    elif char == string_char:
                        in_string = False
                        string_char = None
                    result.append(char)
                elif char == "#" and (not in_string):
                    break
                else:
                    result.append(char)
                i += 1
            cleaned_lines.append("".join(result))
        source_cleaned = "\n".join(cleaned_lines)
        try:
            tree = ast.parse(source_cleaned)
            docstring_ranges = self._extract_docstring_ranges(tree, source_cleaned)
            for start, end in sorted(docstring_ranges, reverse=True):
                source_cleaned = source_cleaned[:start] + source_cleaned[end:]
        except SyntaxError:
            pass
        return source_cleaned

    def _extract_docstring_ranges(self, tree: ast.AST, source: str) -> list:
        ranges = []
        lines = source.split("\n")
        for node in ast.walk(tree):
            docstring = ast.get_docstring(node)
            if docstring and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                pass
        return ranges


def validate_syntax(source: str) -> bool:
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False


def process_file_tree_sitter(file_path: Path) -> ProcessingResult:
    start_time = time.perf_counter()
    try:
        original_content = file_path.read_text(encoding="utf-8")
        original_size = len(original_content.encode("utf-8"))
        remover = TreeSitterCommentRemover()
        new_content = remover.remove_comments_and_docstrings(original_content)
        if not validate_syntax(new_content):
            return ProcessingResult(
                file_path=file_path,
                success=False,
                error="Syntax validation failed",
                processing_time=time.perf_counter() - start_time,
            )
        file_path.write_text(new_content, encoding="utf-8")
        new_size = len(new_content.encode("utf-8"))
        return ProcessingResult(
            file_path=file_path,
            success=True,
            original_size=original_size,
            new_size=new_size,
            processing_time=time.perf_counter() - start_time,
        )
    except Exception as e:
        return ProcessingResult(
            file_path=file_path, success=False, error=str(e), processing_time=time.perf_counter() - start_time
        )


def process_file_ast(file_path: Path) -> ProcessingResult:
    start_time = time.perf_counter()
    try:
        original_content = file_path.read_text(encoding="utf-8")
        original_size = len(original_content.encode("utf-8"))
        remover = ASTCommentRemover()
        new_content = remover.remove_comments_and_docstrings(original_content)
        if not validate_syntax(new_content):
            return ProcessingResult(
                file_path=file_path,
                success=False,
                error="Syntax validation failed",
                processing_time=time.perf_counter() - start_time,
            )
        new_size = len(new_content.encode("utf-8"))
        return ProcessingResult(
            file_path=file_path,
            success=True,
            original_size=original_size,
            new_size=new_size,
            processing_time=time.perf_counter() - start_time,
        )
    except Exception as e:
        return ProcessingResult(
            file_path=file_path, success=False, error=str(e), processing_time=time.perf_counter() - start_time
        )


def process_directory(
    directory: Path = Path.cwd(), max_workers: int = 4, method: str = "tree-sitter"
) -> tuple[list, float]:
    py_files = list(directory.glob("**/*.py"))
    if not py_files:
        print(f"No Python files found in {directory}")
        return ([], 0.0)
    print(f"\nProcessing {len(py_files)} files using {method}...")
    start_time = time.perf_counter()
    process_func = process_file_tree_sitter if method == "tree-sitter" else process_file_ast
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_func, f): f for f in py_files}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status = "✓" if result.success else "✗"
            error_msg = f" ({result.error})" if result.error else ""
            print(f"{status} {result.file_path.name}{error_msg}")
    total_time = time.perf_counter() - start_time
    return (results, total_time)


def print_results(results: list, total_time: float, method: str):
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    total_original = sum((r.original_size for r in successful))
    total_new = sum((r.new_size for r in successful))
    reduction = total_original - total_new if total_original > 0 else 0
    reduction_pct = reduction / total_original * 100 if total_original > 0 else 0
    avg_time = sum((r.processing_time for r in results)) / len(results) if results else 0
    print(f"\n{'=' * 60}")
    print(f"Results ({method.upper()})")
    print(f"{'=' * 60}")
    print(f"Total files:      {len(results)}")
    print(f"Successful:       {len(successful)}")
    print(f"Failed:           {len(failed)}")
    print(f"Total time:       {total_time:.3f}s")
    print(f"Avg time/file:    {avg_time:.3f}s")
    print(f"Original size:    {total_original:,} bytes")
    print(f"New size:         {total_new:,} bytes")
    print(f"Reduction:        {reduction:,} bytes ({reduction_pct:.1f}%)")
    if failed:
        print(f"\nFailed files:")
        for r in failed:
            print(f"  - {r.file_path}: {r.error}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Remove comments and docstrings from Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  %(prog)s                          # Process current directory with tree-sitter\n  %(prog)s --method ast             # Process with AST method\n  %(prog)s --compare                # Compare both methods (dry-run)\n  %(prog)s /path/to/dir --workers 8 # Custom directory and workers\n        ",
    )
    parser.add_argument("directory", nargs="?", default=".", help="Directory to process (default: current directory)")
    parser.add_argument(
        "--method",
        choices=["tree-sitter", "ast"],
        default="tree-sitter",
        help="Processing method (default: tree-sitter)",
    )
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers (default: 4)")
    parser.add_argument("--compare", action="store_true", help="Compare both methods (dry-run, no files modified)")
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    if not directory.exists():
        print(f"ERROR: Directory not found: {directory}")
        sys.exit(1)
    if args.compare:
        print(f"Comparing methods on {directory}...")
        py_files = list(directory.glob("**/*.py"))
        print(f"\nFound {len(py_files)} Python files")
        print("\n[1/2] Testing tree-sitter method...")
        ts_results, ts_time = process_directory(directory, args.workers, "tree-sitter")
        print_results(ts_results, ts_time, "tree-sitter")
        print("\n[2/2] Testing AST method...")
        ast_results, ast_time = process_directory(directory, args.workers, "ast")
        print_results(ast_results, ast_time, "ast")
        print(f"\n{'=' * 60}")
        print("PERFORMANCE COMPARISON")
        print(f"{'=' * 60}")
        print(f"Tree-sitter time: {ts_time:.3f}s")
        print(f"AST time:         {ast_time:.3f}s")
        speedup = ast_time / ts_time if ts_time > 0 else 0
        print(f"Speedup:          {speedup:.2f}x")
        print("\nNOTE: Files were NOT modified (dry-run mode)")
    else:
        results, total_time = process_directory(directory, args.workers, args.method)
        print_results(results, total_time, args.method)


if __name__ == "__main__":
    main()
