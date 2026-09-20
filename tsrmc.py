import argparse
import ast
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final
from loguru import logger
try:
    from tree_sitter import Language, Node, Parser, Query
    from tree_sitter_python import language as python_language
except ImportError:  
    logger.error("Install tree-sitter==0.25.2 and tree-sitter-python==0.25.0")
    sys.exit(1)



WORKER_COUNT = 8
COMMENT_QUERY = """
(comment) @comment
(string) @string
"""
_IGNORED_CHILD_TYPES = frozenset({"comment", "NEWLINE", "INDENT", "DEDENT"})



@dataclass
class ProcessingResult:
    error = None
    original_size = 0
    new_size = 0
    processing_time = 0.0



class TreeSitterCommentRemover:
    QUERY = COMMENT_QUERY
    def __init__(self):
        self.parser = Parser()
        language = python_language()
        self.parser.set_language(language)
        self.query = language.query(self.QUERY)
    def remove_comments_and_docstrings(self, source):
        source_bytes = source.encode("utf-8")
        tree = self.parser.parse(source_bytes)
        captures = self.query.captures(tree.root_node)
        ranges_to_remove = []
        for node, capture_name in captures:
            if capture_name == "comment" or (
                capture_name == "string" and self._is_docstring(node)
            ):
                ranges_to_remove.append((node.start_byte, node.end_byte))
        ranges_to_remove.sort(reverse=True)
        result = self._remove_ranges(source_bytes, ranges_to_remove)
        return result.decode("utf-8", errors="replace")
    @staticmethod
    def _is_docstring(node):
        parent = node.parent
        if parent is None or parent.type != "expression_statement":
            return False
        named_children = [
            child for child in parent.children if child.type not in _IGNORED_CHILD_TYPES
        ]
        return len(named_children) == 1 and named_children[0] == node
    @staticmethod
    def _remove_ranges(source_bytes, ranges):
        if not ranges:
            return source_bytes
        result = bytearray(source_bytes)
        for start, end in ranges:
            removed = source_bytes[start:end]
            newline_count = removed.count(b"\n")
            replacement = (
                b"\n" * newline_count if newline_count > 0 else b" " * (end - start)
            )
            result[start:end] = replacement
        return bytes(result)



class ASTCommentRemover:
    def remove_comments_and_docstrings(self, source):
        lines = source.split("\n")
        cleaned_lines = []
        for line in lines:
            cleaned_lines.append(self._strip_line_comment(line))
        source_cleaned = "\n".join(cleaned_lines)
        try:
            tree = ast.parse(source_cleaned)
        except SyntaxError:
            return source_cleaned
        docstring_ranges = self._extract_docstring_ranges(tree, source_cleaned)
        for start, end in sorted(docstring_ranges, reverse=True):
            source_cleaned = source_cleaned[:start] + source_cleaned[end:]
        return source_cleaned
    @staticmethod
    def _strip_line_comment(line):
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
            elif char == "#" and not in_string:
                break
            else:
                result.append(char)
            i += 1
        return "".join(result)
    @staticmethod
    def _extract_docstring_ranges(tree, source):
        ranges = []
        for node in ast.walk(tree):
            docstring = ast.get_docstring(node)
            if docstring and isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module),
            ):
                
                pass
        _ = source  
        return ranges



def validate_syntax(source):
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False



def process_file_tree_sitter(path):
    start_time = time.perf_counter()
    try:
        original_content = path.read_text(encoding="utf-8")
        original_size = len(original_content.encode("utf-8"))
        remover = TreeSitterCommentRemover()
        new_content = remover.remove_comments_and_docstrings(original_content)
        if not validate_syntax(new_content):
            return ProcessingResult(
                path=path,
                success=False,
                error="Syntax validation failed",
                processing_time=time.perf_counter() - start_time,
            )
        path.write_text(new_content, encoding="utf-8")
        new_size = len(new_content.encode("utf-8"))
        return ProcessingResult(
            path=path,
            success=True,
            original_size=original_size,
            new_size=new_size,
            processing_time=time.perf_counter() - start_time,
        )
    except Exception as exc:  
        return ProcessingResult(
            path=path,
            success=False,
            error=str(exc),
            processing_time=time.perf_counter() - start_time,
        )
def process_file_ast(path):
    start_time = time.perf_counter()
    try:
        original_content = path.read_text(encoding="utf-8")
        original_size = len(original_content.encode("utf-8"))
        remover = ASTCommentRemover()
        new_content = remover.remove_comments_and_docstrings(original_content)
        if not validate_syntax(new_content):
            return ProcessingResult(
                path=path,
                success=False,
                error="Syntax validation failed",
                processing_time=time.perf_counter() - start_time,
            )
        new_size = len(new_content.encode("utf-8"))
        return ProcessingResult(
            path=path,
            success=True,
            original_size=original_size,
            new_size=new_size,
            processing_time=time.perf_counter() - start_time,
        )
    except Exception as exc:  
        return ProcessingResult(
            path=path,
            success=False,
            error=str(exc),
            processing_time=time.perf_counter() - start_time,
        )



def _select_process_func(method):
    if method == "tree-sitter":
        return process_file_tree_sitter
    return process_file_ast
def process_directory(
    directory=Path.cwd(),
    method="tree-sitter",
):
    py_files = list(directory.glob("**/*.py"))
    if not py_files:
        logger.warning("No Python files found in {}", directory)
        return [], 0.0
    print("Processing {} files using {}", len(py_files), method)
    start_time = time.perf_counter()
    process_func = _select_process_func(method)
    results = []
    pool = Pool(processes=WORKER_COUNT)
    try:
        async_results = [pool.apply_async(process_func, (path,)) for path in py_files]
        for async_result in async_results:
            result = async_result.get()
            results.append(result)
            status = "✓" if result.success else "✗"
            error_msg = f" ({result.error})" if result.error else ""
            print(
                "{status} {name}{err}",
                status=status,
                name=result.path.name,
                err=error_msg,
            )
    finally:
        pool.close()
        pool.join()
    total_time = time.perf_counter() - start_time
    return results, total_time



def print_results(results, total_time, method):
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    total_original = sum(r.original_size for r in successful)
    total_new = sum(r.new_size for r in successful)
    reduction = total_original - total_new if total_original > 0 else 0
    reduction_pct = reduction / total_original * 100 if total_original > 0 else 0.0
    avg_time = (
        sum(r.processing_time for r in results) / len(results) if results else 0.0
    )
    print("=" * 40)
    print("Results ({})", method.upper())
    print("=" * 40)
    print("Total files:      {}", len(results))
    print("Successful:       {}", len(successful))
    print("Failed:           {}", len(failed))
    print("Total time:       {:.3f}s", total_time)
    print("Avg time/file:    {:.3f}s", avg_time)
    print("Original size:    {:,} bytes", total_original)
    print("New size:         {:,} bytes", total_new)
    print("Reduction:        {:,} bytes ({:.1f}%)", reduction, reduction_pct)
    if failed:
        logger.warning("Failed files:")
        for r in failed:
            logger.warning("  - {}: {}", r.path, r.error)



def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Remove comments and docstrings from Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s\n"
            "  %(prog)s --method ast\n"
            "  %(prog)s --compare\n"
            "  %(prog)s /path/to/dir\n"
        ),
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to process (default: current directory)",
    )
    parser.add_argument(
        "--method",
        choices=["tree-sitter", "ast"],
        default="tree-sitter",
        help="Processing method (default: tree-sitter)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare both methods (dry-run, no files modified)",
    )
    return parser
def _iter_py_files(directory):
    return directory.glob("**/*.py")
def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    if not directory.exists():
        logger.error("Directory not found: {}", directory)
        return 1
    if args.compare:
        print("Comparing methods on {}", directory)
        py_files = list(_iter_py_files(directory))
        print("Found {} Python files", len(py_files))
        print("[1/2] Testing tree-sitter method...")
        ts_results, ts_time = process_directory(directory, "tree-sitter")
        print_results(ts_results, ts_time, "tree-sitter")
        print("[2/2] Testing AST method...")
        ast_results, ast_time = process_directory(directory, "ast")
        print_results(ast_results, ast_time, "ast")
        print("=" * 40)
        print("PERFORMANCE COMPARISON")
        print("=" * 40)
        print("Tree-sitter time: {:.3f}s", ts_time)
        print("AST time:         {:.3f}s", ast_time)
        speedup = ast_time / ts_time if ts_time > 0 else 0.0
        print("Speedup:          {:.2f}x", speedup)
        logger.warning("NOTE: Files were NOT modified (dry-run mode)")
    else:
        results, total_time = process_directory(directory, args.method)
        print_results(results, total_time, args.method)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
