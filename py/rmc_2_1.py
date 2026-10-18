#!/data/data/com.termux/files/usr/bin/python
import argparse
import sys
from pathlib import Path
import libcst as cst


class CommentStripper(cst.CSTTransformer):
    def leave_TrailingWhitespace(
        self, original_node: cst.TrailingWhitespace, updated_node: cst.TrailingWhitespace
    ) -> cst.TrailingWhitespace:
        return updated_node.with_changes(comment=None)

    def leave_EmptyLine(self, original_node: cst.EmptyLine, updated_node: cst.EmptyLine) -> cst.EmptyLine:
        if updated_node.comment is not None:
            return updated_node.with_changes(comment=None)
        return updated_node


class DocstringStripper(cst.CSTTransformer):
    def _is_docstring(self, node) -> bool:
        return isinstance(node, cst.Expr) and isinstance(node.value, (cst.SimpleString, cst.ConcatenatedString))

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        if updated_node.body and self._is_docstring(updated_node.body[0]):
            return updated_node.with_changes(body=updated_node.body[1:])
        return updated_node

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        body_seq = updated_node.body.body
        if body_seq and self._is_docstring(body_seq[0]):
            items = list(body_seq)
            new_body = [cst.SimpleStatementLine([cst.Pass()])] if len(items) == 1 else items[1:]
            return updated_node.with_changes(body=updated_node.body.with_changes(body=new_body))
        return updated_node

    def leave_AsyncFunctionDef(
        self, original_node: cst.AsyncFunctionDef, updated_node: cst.AsyncFunctionDef
    ) -> cst.AsyncFunctionDef:
        body_seq = updated_node.body.body
        if body_seq and self._is_docstring(body_seq[0]):
            items = list(body_seq)
            new_body = [cst.SimpleStatementLine([cst.Pass()])] if len(items) == 1 else items[1:]
            return updated_node.with_changes(body=updated_node.body.with_changes(body=new_body))
        return updated_node

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        body_seq = updated_node.body.body
        if body_seq and self._is_docstring(body_seq[0]):
            items = list(body_seq)
            new_body = [cst.SimpleStatementLine([cst.Pass()])] if len(items) == 1 else items[1:]
            return updated_node.with_changes(body=updated_node.body.with_changes(body=new_body))
        return updated_node


def discover_python_files(inputs):
    for path in inputs:
        p = Path(path).resolve()
        if p.is_file() and p.suffix.lower() == ".py":
            yield p
        elif p.is_dir():
            for child in p.rglob("*.py"):
                if child.is_file():
                    yield child


def process_file(file_path: Path, strip_comments: bool, strip_docstrings: bool) -> int:
    original_bytes = file_path.read_bytes()
    code = original_bytes.decode("utf-8", errors="replace")

    # Parse with LibCST
    module = cst.parse_module(code)

    # Apply requested transformations
    if strip_comments:
        module = module.visit(CommentStripper())
    if strip_docstrings:
        module = module.visit(DocstringStripper())

    new_code = module.code

    # Validate resulting code syntax
    cst.parse_module(new_code)

    new_bytes = new_code.encode("utf-8")
    file_path.write_bytes(new_bytes)

    reduced = len(original_bytes) - len(new_bytes)
    return reduced


def format_bytes(cr: int, use_color: bool = True) -> str:
    dB = f"{cr:,}"
    if not use_color:
        return dB
    if cr == 0:
        return f"\x1b[2m{dB}\x1b[0m"  # Dim
    return f"\x1b[32m{dB}\x1b[0m"  # Green


def main():
    parser = argparse.ArgumentParser(description="Strip comments and/or docstrings from Python files using LibCST.")
    parser.add_argument(
        "inputs", nargs="*", type=Path, help="Files or directories to process (default: current directory)"
    )
    parser.add_argument("-c", action="store_true", help="Remove all comments")
    parser.add_argument("-d", action="store_true", help="Remove all docstrings")
    parser.add_argument("-a", "--all", action="store_true", help="Remove all comments and docstrings")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto", help="Color output")

    args = parser.parse_args()

    inputs = args.inputs if args.inputs else [Path(".")]

    strip_comments = args.c or args.all
    strip_docstrings = args.d or args.all

    if not strip_comments and not strip_docstrings:
        print("Error: Specify at least one flag: -c, -d, or -a.", file=sys.stderr)
        sys.exit(1)

    py_files = list(discover_python_files(inputs))
    if not py_files:
        print("No Python files found.")
        sys.exit(0)

    use_color = args.color == "always" or (
        args.color == "auto" and sys.stdout.isatty() and "NO_COLOR" not in __import__("os").environ
    )

    max_name_len = max((len(f.name) for f in py_files), default=0)
    total_space_freed = 0
    processed_count = 0
    error_count = 0

    for file_path in py_files:
        try:
            reduced = process_file(file_path, strip_comments, strip_docstrings)
            total_space_freed += reduced
            processed_count += 1
            print(f"{file_path.name:<{max_name_len}}    {format_bytes(reduced, use_color)}")
        except Exception as exc:
            error_count += 1
            print(f"{file_path.name:<{max_name_len}}    Error: {exc}", file=sys.stderr)

    print("\n--- Summary ---")
    print(f"Successfully processed: {processed_count} file(s)")
    if error_count > 0:
        print(f"Errors encountered: {error_count} file(s)")
    print(f"Overall space freed: {format_bytes(total_space_freed, use_color)} bytes")


if __name__ == "__main__":
    main()
