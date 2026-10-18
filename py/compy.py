import ast
import builtins
import string
import sys
from pathlib import Path

PROTECTED_NAMES = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__main__", "self", "cls"}


class StripDocstringsAndTypes(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        node.returns = None
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        node.returns = None
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_Module(self, node):
        self._remove_docstring(node)
        self.generic_visit(node)
        return node

    def visit_arg(self, node):
        node.annotation = None
        return node

    def visit_AnnAssign(self, node):
        if node.value is None:
            return None
        return self.visit(ast.Assign(targets=[node.target], value=node.value))

    def _remove_docstring(self, node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)


def generate_short_names():
    letters = string.ascii_lowercase
    idx = 0
    while True:
        if idx < 26:
            yield letters[idx]
        else:
            yield f"{letters[idx % 26]}{idx // 26}"
        idx += 1


class NameCollector(ast.NodeVisitor):
    def __init__(self, name_map, name_gen):
        self.name_map = name_map
        self.name_gen = name_gen

    def _register(self, name):
        if (
            name
            and len(name) > 3
            and name not in PROTECTED_NAMES
            and not name.startswith("__")
            and name not in self.name_map
        ):
            self.name_map[name] = next(self.name_gen)

    def visit_FunctionDef(self, node):
        self._register(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._register(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self._register(node.name)
        self.generic_visit(node)

    def visit_arg(self, node):
        self._register(node.arg)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self._register(node.id)


class NameRenamer(ast.NodeTransformer):
    def __init__(self, name_map):
        self.name_map = name_map

    def visit_FunctionDef(self, node):
        node.name = self.name_map.get(node.name, node.name)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        node.name = self.name_map.get(node.name, node.name)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        node.name = self.name_map.get(node.name, node.name)
        self.generic_visit(node)
        return node

    def visit_arg(self, node):
        node.arg = self.name_map.get(node.arg, node.arg)
        return node

    def visit_Name(self, node):
        node.id = self.name_map.get(node.id, node.id)
        return node


def compress_files(file_paths):
    name_map = {}
    name_gen = generate_short_names()
    parsed_trees = []
    for filepath in file_paths:
        path = Path(filepath)
        if not path.exists():
            print(f"Warning: File '{filepath}' not found. Skipping.", file=sys.stderr)
            continue
        code = path.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=filepath)
        tree = StripDocstringsAndTypes().visit(tree)
        ast.fix_missing_locations(tree)
        NameCollector(name_map, name_gen).visit(tree)
        parsed_trees.append((filepath, tree))
    output_parts = []
    for filepath, tree in parsed_trees:
        tree = NameRenamer(name_map).visit(tree)
        ast.fix_missing_locations(tree)
        minified_code = ast.unparse(tree)
        cleaned_lines = [line for line in minified_code.splitlines() if line.strip()]
        header = f"# --- File: {filepath} ---"
        output_parts.append(header + "\n" + "\n".join(cleaned_lines))
    compressed_content = "\n\n".join(output_parts)
    Path("compressed.py").write_text(compressed_content, encoding="utf-8")
    print(f"Compressed {len(parsed_trees)} file(s) into 'compressed.py'.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compressor.py <file1.py> [file2.py ...]")
        sys.exit(1)
    compress_files(sys.argv[1:])
