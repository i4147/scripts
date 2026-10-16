#!/data/data/com.termux/files/usr/bin/env python

from __future__ import annotations
import ast
import sys
from pathlib import Path


def has_main_guard(filepath: Path) -> bool:
    try:
        source = filepath.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        print(f"  ! Could not read {filepath.name}: {e}", file=sys.stderr)
        return True
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        print(f"  ! Syntax error in {filepath.name}: {e}", file=sys.stderr)
        return True
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare):
            continue
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            continue
        left, right = test.left, test.comparators[0]

        def is_dunder_name(n):
            return isinstance(n, ast.Name) and n.id == "__name__"

        def is_main_string(n):
            return isinstance(n, ast.Constant) and n.value == "__main__"

        if (is_dunder_name(left) and is_main_string(right)) or (is_dunder_name(right) and is_main_string(left)):
            return True
    return False


def main():
    from fastwalk import walk_files

    cwd = Path.cwd()
    for p in walk_files(cwd):
        if p.is_file() and p.suffix == ".py" and p.name != Path(__file__).name and not has_main_guard(p):
            print(p.name)


if __name__ == "__main__":
    sys.exit(main())
