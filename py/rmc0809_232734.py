from __future__ import annotations

import ast
import sys
from argparse import ArgumentParser
from multiprocessing import Pool
from pathlib import Path

try:
    import tree_sitter_python as tspython
    from tree_sitter import Language, Parser
except ImportError:
    print("Error: Install with: pip install tree-sitter==0.26.0 tree-sitter-python==0.25.0")
    sys.exit(1)


class CommentDocstringRemover:
    SKIP_DIRS = {".git", "__pycache__", ".venv", "venv"}
    PRESERVE_PATTERNS = {"# fmt:", "# type:", "# noqa", "# pragma:", "# pylint:"}

    def __init__(self, remove_module_docstring=False):
        self.remove_module_docstring = remove_module_docstring

    def _walk_files(self, paths):
        for path in paths:
            p = Path(path).resolve()
            if p.is_file() and p.suffix == ".py":
                yield p
            elif p.is_dir():
                yield from self._recursive_walk(p)

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

    def _is_module_docstring(self, node, tree, source):
        if node.type != "string":
            return False
        parent = node.parent
        if parent.type not in ("expression_statement", "module"):
            return False
        if parent.type == "expression_statement":
            module_body = [c for c in tree.root_node.children if c.type not in ("comment",)]
            return module_body and module_body[0] == parent
        return False

    def _should_preserve_comment(self, text):
        stripped = text.lstrip("#").strip()
        return any(stripped.startswith(p) for p in self.PRESERVE_PATTERNS)

    def _find_docstrings(self, node):
        if node.type == "string":
            yield node
        for child in node.children:
            yield from self._find_docstrings(child)

    def process_file(self, filepath, parser):
        try:
            source = filepath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            return filepath, {"comments": 0, "docstrings": 0, "error": str(e)}

        tree = parser.parse(source.encode("utf-8"))
        removals = []

        for node in self._find_docstrings(tree.root_node):
            if self._is_module_docstring(node, tree, source) and not self.remove_module_docstring:
                continue
            removals.append((node.start_byte, node.end_byte))

        for node in tree.root_node.children:
            if node.type == "comment" and not self._should_preserve_comment(source[node.start_byte : node.end_byte]):
                removals.append((node.start_byte, node.end_byte))

        if not removals:
            return filepath, {"comments": 0, "docstrings": 0, "changed": False}

        removals.sort(reverse=True)
        modified = source
        for start, end in removals:
            modified = modified[:start] + modified[end:]

        try:
            ast.parse(modified)
        except SyntaxError:
            return filepath, {"comments": 0, "docstrings": 0, "error": "SyntaxError after removal"}

        filepath.write_text(modified, encoding="utf-8")
        doc_count = sum(1 for start, end in removals if source[start : start + 1] in ('"', "'"))
        comment_count = len(removals) - doc_count

        return filepath, {"comments": comment_count, "docstrings": doc_count, "changed": True}


def _init_worker():
    global parser
    language = Language(tspython.language())
    parser = Parser(language)


def _process_wrapper(args):
    filepath, remove_module_docstring = args
    remover = CommentDocstringRemover(remove_module_docstring)
    return remover.process_file(filepath, parser)


def main():
    parser_arg = ArgumentParser()
    parser_arg.add_argument("paths", nargs="*", default=["."])
    parser_arg.add_argument("-r", "--remove-module-docstrings", action="store_true")
    parser_arg.add_argument("-j", "--jobs", type=int, default=6)
    args = parser_arg.parse_args()

    remover = CommentDocstringRemover(args.remove_module_docstrings)
    files = list(remover._walk_files(args.paths))

    if not files:
        print("No Python files found.")
        return

    with Pool(processes=args.jobs, initializer=_init_worker) as pool:
        results = pool.imap_unordered(_process_wrapper, ((f, args.remove_module_docstrings) for f in files))
        total_comments = total_docstrings = 0
        for filepath, stats in results:
            if "error" in stats:
                print(f"✗ {filepath.relative_to(Path.cwd())}: {stats['error']}")
            elif stats.get("changed"):
                print(f"✓ {filepath}: {stats['comments']} comments, {stats['docstrings']} docstrings")
                total_comments += stats["comments"]
                total_docstrings += stats["docstrings"]

    print(f"\nTotal: {total_comments} comments, {total_docstrings} docstrings removed")


if __name__ == "__main__":
    main()
