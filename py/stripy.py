
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Sequence

import libcst as cst







def _pass_stmt() -> cst.SimpleStatementLine:
    return cst.SimpleStatementLine(body=[cst.Pass()])


def _is_docstring_small(stmt: cst.BaseSmallStatement) -> bool:
    return isinstance(stmt, cst.Expr) and isinstance(stmt.value, (cst.SimpleString, cst.ConcatenatedString))


def _is_docstring_stmt(stmt: cst.BaseStatement) -> bool:
    if not isinstance(stmt, cst.SimpleStatementLine):
        return False
    if len(stmt.body) != 1:
        return False
    return _is_docstring_small(stmt.body[0])


def _strip_first_docstring(
    stmts: Sequence[cst.BaseStatement],
    ensure_body: bool = False,
) -> Sequence[cst.BaseStatement]:
    new = list(stmts)
    if new and _is_docstring_stmt(new[0]):
        new = new[1:]
    if ensure_body and not new:
        new = [_pass_stmt()]
    return new


def _strip_suite(body: cst.BaseSuite, ensure_body: bool = True) -> cst.BaseSuite:
    if isinstance(body, cst.IndentedBlock):
        new_inner = _strip_first_docstring(body.body, ensure_body=ensure_body)
        return body.with_changes(body=new_inner)

    if isinstance(body, cst.SimpleStatementSuite):
        new_inner = list(body.body)
        if new_inner and _is_docstring_small(new_inner[0]):
            new_inner = new_inner[1:]
        if ensure_body and not new_inner:
            new_inner = [cst.Pass()]
        return body.with_changes(body=new_inner)

    return body







class StripTransformer(cst.CSTTransformer):
    

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        
        return updated_node.with_changes(body=_strip_first_docstring(updated_node.body, ensure_body=False))

    def _strip_func(self, updated_node):
        new_body = _strip_suite(updated_node.body, ensure_body=True)
        if new_body is updated_node.body:
            return updated_node
        return updated_node.with_changes(body=new_body)

    def leave_FunctionDef(self, original_node, updated_node):
        return self._strip_func(updated_node)

    def leave_AsyncFunctionDef(self, original_node, updated_node):
        return self._strip_func(updated_node)

    def leave_ClassDef(self, original_node, updated_node):
        new_body = _strip_suite(updated_node.body, ensure_body=True)
        if new_body is updated_node.body:
            return updated_node
        return updated_node.with_changes(body=new_body)

    

    def leave_TrailingWhitespace(self, original_node, updated_node):
        if updated_node.comment is not None:
            return updated_node.with_changes(comment=None)
        return updated_node

    def leave_EmptyLine(self, original_node, updated_node):
        if updated_node.comment is not None:
            return updated_node.with_changes(comment=None)
        return updated_node







def process_file(path: Path) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"  skip (not utf-8): {path}", file=sys.stderr)
        return False

    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        print(f"  skip (parse error): {path}: {exc}", file=sys.stderr)
        return False

    new_code = module.visit(StripTransformer()).code
    if new_code == source:
        return False

    
    try:
        ast.parse(new_code)
    except SyntaxError as exc:
        print(
            f"  skip (invalid output, not writing): {path}: {exc}",
            file=sys.stderr,
        )
        return False
    try:
        cst.parse_module(new_code)
    except cst.ParserSyntaxError as exc:
        print(
            f"  skip (libcst rejects output, not writing): {path}: {exc}",
            file=sys.stderr,
        )
        return False

    path.write_text(new_code, encoding="utf-8")
    return True







def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 1

    changed = 0
    total = 0
    for path in sorted(root.rglob("*.py")):
        total += 1
        if process_file(path):
            changed += 1
            print(f"  updated {path}")

    print(f"\nDone. {changed}/{total} file(s) modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
