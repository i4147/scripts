import sys
import ast
from pathlib import Path
from multiprocessing import Pool
from argparse import ArgumentParser
from functools import partial

try:
    from tree_sitter import Language, Parser
    from tree_sitter_python import language as python_language
except ImportError:
    print("Error: tree-sitter required. Install with: pip install tree-sitter tree-sitter-python")
    sys.exit(1)


class CommentDocstringRemover:
    SKIP_DIRS = {".git", "__pycache__", ".venv", "venv"}
    PRESERVE_PATTERNS = {"# fmt:", "# type:", "# noqa", "# pragma:", "# pylint:"}

    def __init__(self, remove_module_docstring=False):
        self.parser = Parser()
        self.parser.set_language(python_language)
        self.remove_module_docstring = remove_module_docstring
        self.stats = {"comments": 0, "docstrings": 0}

    def _walk_files(self, paths):
        for path in paths:
            p = Path(path).resolve()
            if p.is_file() and p.suffix == ".py":
                yield p
            elif p.is_dir():
                for py_file in self._recursive_walk(p):
                    yield py_file

    def _recursive_walk(self, directory):
        try:
            for item in directory.iterdir():
                if item.is_symlink():
                    continue
                if item.is_dir() and item.name not in self.SKIP_DIRS:
                    yield from self._recursive_walk(item)
                elif item.is_file() and item.suffix == ".py":
                    yield item
        except (PermissionError, OSError):
            pass

    def _is_module_docstring(self, node, tree):
        if node.type != "string":
            return False
        parent = node.parent
        if parent.type not in ("expression_statement", "module"):
            return False
        if parent.type == "expression_statement":
            if parent.parent.type != "module":
                return False
            module_children = tree.root_node.children
            for i, child in enumerate(module_children):
                if child.type == "comment":
                    continue
                if child == parent:
                    return i == sum(1 for c in module_children[:i] if c.type == "comment")
                break
        return False

    def _should_preserve_comment(self, text):
        stripped = text.lstrip("#").strip()
        for pattern in self.PRESERVE_PATTERNS:
            if stripped.startswith(pattern):
                return True
        return False

    def _find_string_nodes(self, node):
        if node.type == "string":
            yield node
        for child in node.children:
            yield from self._find_string_nodes(child)

    def _needs_pass_replacement(self, node):
        if node.type not in ("function_definition", "class_definition"):
            return False
        body_nodes = [n for n in node.children if n.type == "block"]
        if not body_nodes:
            return False
        block = body_nodes[0]
        statements = [n for n in block.children if n.type in ("simple_statement", "string", "expression_statement")]
        statements = [s for s in statements if s.type != "comment"]
        if len(statements) == 1 and statements[0].type in ("string", "expression_statement"):
            if statements[0].type == "expression_statement":
                expr_child = next((c for c in statements[0].children if c.type == "string"), None)
                return expr_child is not None
            return statements[0].type == "string"
        return False

    def process_file(self, filepath):
        try:
            source = filepath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            return filepath, {"comments": 0, "docstrings": 0, "error": str(e)}

        tree = self.parser.parse(source.encode("utf-8"))
        lines = source.splitlines(keepends=True)
        removals = []
        docstring_count = 0
        comment_count = 0

        for node in self._find_string_nodes(tree.root_node):
            if self._is_module_docstring(node, tree) and not self.remove_module_docstring:
                continue
            start_byte = node.start_byte
            end_byte = node.end_byte
            removals.append((start_byte, end_byte, "docstring"))
            docstring_count += 1

        for node in tree.root_node.children:
            if node.type == "comment":
                text = source[node.start_byte : node.end_byte]
                if not self._should_preserve_comment(text):
                    removals.append((node.start_byte, node.end_byte, "comment"))
                    comment_count += 1

        if not removals:
            return filepath, {"comments": 0, "docstrings": 0, "changed": False}

        removals.sort(reverse=True)
        modified = source
        for start, end, _ in removals:
            modified = modified[:start] + modified[end:]

        modified = self._remove_trailing_newlines(modified)

        try:
            ast.parse(modified)
        except SyntaxError:
            modified = self._add_pass_statements(modified, filepath)
            try:
                ast.parse(modified)
            except SyntaxError as e:
                return filepath, {"comments": 0, "docstrings": 0, "error": f"SyntaxError: {e}"}

        if modified != source:
            try:
                filepath.write_text(modified, encoding="utf-8")
            except OSError as e:
                return filepath, {"comments": 0, "docstrings": 0, "error": f"Write failed: {e}"}

        return filepath, {"comments": comment_count, "docstrings": docstring_count, "changed": True}

    def _remove_trailing_newlines(self, source):
        lines = source.splitlines(keepends=True)
        while lines and lines[-1].strip() == "":
            lines.pop()
        return "".join(lines)

    def _add_pass_statements(self, source, filepath):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.body or (
                    len(node.body) == 1
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                ):
                    lines = source.splitlines(keepends=True)
                    indent = len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip())
                    node.body = [ast.Pass()]

        try:
            return ast.unparse(tree)
        except Exception:
            return source


def process_file_wrapper(args):
    remover, filepath = args
    return remover.process_file(filepath)


def main():
    parser = ArgumentParser(description="Remove comments and docstrings from Python files using tree-sitter")
    parser.add_argument(
        "paths", nargs="*", default=["."], help="Files or directories to process (default: current directory)"
    )
    parser.add_argument(
        "-r", "--remove-module-docstrings", action="store_true", help="Also remove module-level docstrings"
    )
    parser.add_argument("-j", "--jobs", type=int, default=None, help="Number of parallel jobs (default: CPU count)")
    args = parser.parse_args()

    remover = CommentDocstringRemover(remove_module_docstring=args.remove_module_docstrings)
    files = list(remover._walk_files(args.paths))

    if not files:
        print("No Python files found.")
        return

    with Pool(processes=args.jobs) as pool:
        results = pool.imap_unordered(process_file_wrapper, ((remover, f) for f in files))
        total_comments = 0
        total_docstrings = 0
        for filepath, stats in results:
            if "error" in stats:
                print(f"✗ {filepath.relative_to(Path.cwd())}: {stats['error']}")
            elif stats.get("changed"):
                print(
                    f"✓ {filepath.relative_to(Path.cwd())}: {stats['comments']} comments, {stats['docstrings']} docstrings removed"
                )
                total_comments += stats["comments"]
                total_docstrings += stats["docstrings"]

    print(f"\nTotal: {total_comments} comments, {total_docstrings} docstrings removed")


if __name__ == "__main__":
    main()
