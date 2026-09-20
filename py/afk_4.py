


import ast
import multiprocessing
from pathlib import Path
import sys
from typing import Dict, List, Set, Tuple

import pyflakes.api
import pyflakes.messages
import pyflakes.reporter
from dh import get_pyfiles


class UnusedImportCollector(pyflakes.reporter.Reporter):

    def __init__(self) -> None:
        super().__init__()
        self.unused: List[pyflakes.messages.UnusedImport] = []

    def unexpectedError(self, filename, msg) -> None:
        pass

    def syntaxError(self, filename, msg, lineno, offset, text) -> None:
        pass

    def flake(self, msg) -> None:
        if isinstance(msg, pyflakes.messages.UnusedImport):
            self.unused.append(msg)


def get_unused_imports(path: Path) -> List[pyflakes.messages.UnusedImport]:
    try:
        source = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading {path}: {e}", file=sys.stderr)
        return []
    reporter = UnusedImportCollector()
    try:
        pyflakes.api.check(source, str(path), reporter=reporter)
    except Exception as e:
        print(f"Error checking {path}: {e}", file=sys.stderr)
        return []
    return reporter.unused


def process_file(path: str | Path) -> Tuple[str, List[str]]:
    path = Path(path)
    unused_msgs = get_unused_imports(path)
    if not unused_msgs:
        return (str(path), [])

    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"Syntax error in {path}: {e}", file=sys.stderr)
        return (str(path), [])

    
    line_unused: Dict[int, Set[str]] = {}
    for msg in unused_msgs:
        line_unused.setdefault(msg.lineno, set()).add(msg.name)

    removed_names: List[str] = []

    class ImportTransformer(ast.NodeTransformer):
        def visit_Import(self, node):
            if node.lineno in line_unused:
                unused_set = line_unused[node.lineno]
                new_aliases = []
                for alias in node.names:
                    bound_name = alias.asname if alias.asname else alias.name
                    if bound_name in unused_set:
                        removed_names.append(bound_name)
                    else:
                        new_aliases.append(alias)
                if not new_aliases:
                    
                    return ast.Pass()
                node.names = new_aliases
            return node

        def visit_ImportFrom(self, node):
            if node.lineno in line_unused:
                unused_set = line_unused[node.lineno]
                new_names = []
                for alias in node.names:
                    
                    if alias.name == "*":
                        new_names.append(alias)
                        continue
                    bound_name = alias.asname if alias.asname else alias.name
                    if bound_name in unused_set:
                        removed_names.append(bound_name)
                    else:
                        new_names.append(alias)
                if not new_names:
                    return ast.Pass()
                node.names = new_names
            return node

    transformer = ImportTransformer()
    new_tree = transformer.visit(tree)
    ast.fix_missing_locations(new_tree)

    new_source = ast.unparse(new_tree)
    path.write_text(new_source, encoding="utf-8")
    return (str(path), removed_names)


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_pyfiles(cwd)

    if not files:
        print("No Python files found.")
        return
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    with multiprocessing.Pool() as pool:
        results = pool.map(process_file, files)

    
    for path, removed in results:
        if removed:
            print(f"{path}: removed {', '.join(removed)}")


if __name__ == "__main__":
    main()
