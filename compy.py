#!/data/data/com.termux/files/home/.local/bin/python
import ast
import builtins
import keyword
import os
import sys

class LLMCompressor(ast.NodeTransformer):
    """AST Transformer to strip docstrings, type annotations, and shorten long identifiers."""
    
    def __init__(self, min_length_to_shorten=8):
        self.min_length = min_length_to_shorten
        self.name_map = {}
        self.counter = 0
        # Prevent renaming Python builtins, keywords, and common convention names
        self.protected = set(dir(builtins)) | set(keyword.kwlist) | {
            "self", "cls", "main", "__name__", "__doc__", "__file__", "__init__"
        }

    def _get_short_name(self, old_name: str) -> str:
        if old_name in self.protected or old_name.startswith("__"):
            return old_name
        if len(old_name) < self.min_length:
            return old_name
        if old_name not in self.name_map:
            self.name_map[old_name] = f"v{self.counter}"
            self.counter += 1
        return self.name_map[old_name]

    def _strip_docstring(self, node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)

    def visit_FunctionDef(self, node):
        self._strip_docstring(node)
        node.returns = None
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        self._strip_docstring(node)
        node.returns = None
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        self._strip_docstring(node)
        self.generic_visit(node)
        return node

    def visit_Module(self, node):
        self._strip_docstring(node)
        self.generic_visit(node)
        return node

    def visit_arg(self, node):
        node.annotation = None
        node.arg = self._get_short_name(node.arg)
        return node

    def visit_AnnAssign(self, node):
        self.generic_visit(node)
        if node.value is None:
            return None  # Remove variable declarations without assignment (e.g. `x: int`)
        return ast.Assign(targets=[node.target], value=node.value)  # Convert `x: int = 5` to `x = 5`

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Load, ast.Store, ast.Del)):
            node.id = self._get_short_name(node.id)
        return node


def compress_files(file_paths):
    if not file_paths:
        print("Usage: python compressor.py <file1.py> [file2.py ...]")
        sys.exit(1)

    output_chunks = []
    is_multi_file = len(file_paths) > 1

    for filepath in file_paths:
        if not os.path.exists(filepath):
            print(f"Skipping: '{filepath}' (file not found)", file=sys.stderr)
            continue

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()

            tree = ast.parse(source, filename=filepath)
            transformer = LLMCompressor()
            transformed_tree = transformer.visit(tree)
            ast.fix_missing_locations(transformed_tree)

            # Unparse AST back into source code (automatically drops comments)
            clean_code = ast.unparse(transformed_tree)

            # Strip all blank/empty lines
            non_empty_lines = [line for line inHere is the Python script to compress `.py` files using Python's built-in `ast` module. It strips docstrings, comments, type annotations, removes empty lines, shortens user-defined identifier names (variables, functions, arguments, classes), and merges multiple files into `compressed.py`.

Save the following script as `compressor.py`:

```python
import ast
import builtins
import string
import sys
from pathlib import Path

# Built-ins and common special identifiers to protect from renaming
PROTECTED_NAMES = (
    set(dir(builtins))
    | {"__file__", "__name__", "__doc__", "__main__", "self", "cls"}
)


class StripDocstringsAndTypes(ast.NodeTransformer):
    """Removes docstrings, function return types, parameter type hints, and type annotations."""

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
        # Convert annotated assignment `x: int = 1` -> `x = 1`
        if node.value is None:
            return None  # Drop variable declarations without values (e.g., `x: int`)
        return self.visit(
            ast.Assign(targets=[node.target], value=node.value)
        )

    def _remove_docstring(self, node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)


def generate_short_names():
    """Generates short variable names: a, b, ..., z, a1, b1, ..."""
    letters = string.ascii_lowercase
    idx = 0
    while True:
        if idx < 26:
            yield letters[idx]
        else:
            yield f"{letters[idx % 26]}{idx // 26}"
        idx += 1


class NameCollector(ast.NodeVisitor):
    """Collects user-defined identifiers longer than 3 characters."""

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
    """Replaces collected identifiers with shortened names."""

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

    # First pass: Parse AST and collect identifiers across all files
    for filepath in file_paths:
        path = Path(filepath)
        if not path.exists():
            print(f"Warning: File '{filepath}' not found. Skipping.", file=sys.stderr)
            continue

        code = path.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=filepath)

        # Strip types and docstrings
        tree = StripDocstringsAndTypes().visit(tree)
        ast.fix_missing_locations(tree)

        # Collect variable/function names for shortening
        NameCollector(name_map, name_gen).visit(tree)
        parsed_trees.append((filepath, tree))

    # Second pass: Rename identifiers and generate compressed code
    output_parts = []
    for filepath, tree in parsed_trees:
        tree = NameRenamer(name_map).visit(tree)
        ast.fix_missing_locations(tree)

        # ast.unparse removes original comments and extra whitespace
        minified_code = ast.unparse(tree)

        # Remove extra blank lines
        cleaned_lines = [line for line in minified_code.splitlines() if line.strip()]
        header = f"# --- File: {filepath} ---"
        output_parts.append(header + "\n" + "\n".join(cleaned_lines))

    # Save output
    compressed_content = "\n\n".join(output_parts)
    Path("compressed.py").write_text(compressed_content, encoding="utf-8")
    print(f"Compressed {len(parsed_trees)} file(s) into 'compressed.py'.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compressor.py <file1.py> [file2.py ...]")
        sys.exit(1)

    compress_files(sys.argv[1:])
