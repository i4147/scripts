#!/data/data/com.termux/files/usr/bin/python
import argparse
import sys
import os
from pathlib import Path
import multiprocessing as mp
import libcst as cst
from dh import should_skip
from fastwalk import walk_files


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


def worker_process(args):
    file_path, strip_comments, strip_docstrings = args
    try:
        original_bytes = file_path.read_bytes()
        code = original_bytes.decode("utf-8", errors="replace")

        module = cst.parse_module(code)

        if strip_comments:
            module = module.visit(CommentStripper())
        if strip_docstrings:
            module = module.visit(DocstringStripper())

        new_code = module.code
        cst.parse_module(new_code)  # Validate syntax

        new_bytes = new_code.encode("utf-8")
        file_path.write_bytes(new_bytes)

        reduced = len(original_bytes) - len(new_bytes)
        return file_path, reduced, None
    except Exception as exc:
        return file_path, 0, str(exc)


def discover_python_files(inputs):
    for path in inputs:
        p = Path(path).resolve()
        if p.is_file() and p.suffix.lower() == ".py":
            yield p
        elif p.is_dir():
            for child in walk_files(p, follow_links=False):
                if child.is_file() and not should_skip(child):
                    yield child


def format_bytes(cr: int, use_color: bool = True) -> str:
    dB = f"{cr:,}"
    if not use_color:
        return dB
    if cr == 0:
        return f"\x1b[2m{dB}\x1b[0m"  # Dim for 0
    return f"\x1b[32m{dB}\x1b[0m"  # Green for non-zero


def main():
    parser = argparse.ArgumentParser(description="Strip comments and/or docstrings from Python files using LibCST.")
    parser.add_argument(
        "inputs", nargs="*", type=Path, help="Files or directories to process (default: current directory)"
    )
    parser.add_argument("-c", action="store_true", help="Remove all comments")
    parser.add_argument("-d", action="store_true", help="Remove all docstrings")
    parser.add_argument("-a", "--all", action="store_true", help="Remove all comments and docstrings")
    parser.add_argument(
        "-j", "--workers", type=int, default=1, help="Number of parallel workers (default: 1, no multiprocessing)"
    )
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto", help="Color output")

    args = parser.parse_args()

    inputs = args.inputs if args.inputs else [Path(".")]

    strip_comments = args.c or args.all
    strip_docstrings = args.d or args.all

    if not strip_comments and not strip_docstrings:
        print("Error: Specify at least one flag: -c, -d, or -a.", file=sys.stderr)
        sys.exit(1)

    use_color = args.color == "always" or (
        args.color == "auto" and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    )

    total_space_freed = 0
    processed_count = 0
    error_count = 0
    found_any = False

    # Lazy task generator
    file_generator = discover_python_files(inputs)
    task_generator = ((f, strip_comments, strip_docstrings) for f in file_generator)

    def handle_result(file_path, reduced, err):
        nonlocal total_space_freed, processed_count, error_count, found_any
        found_any = True
        if err:
            error_count += 1
            print(f"{file_path.name}    Error: {err}", file=sys.stderr)
        else:
            total_space_freed += reduced
            processed_count += 1
            print(f"{file_path.name}    {format_bytes(reduced, use_color)}")
            sys.stdout.flush()

    # Process immediately as files stream in
    if args.workers <= 1:
        for task in task_generator:
            file_path, reduced, err = worker_process(task)
            handle_result(file_path, reduced, err)
    else:
        with mp.Pool(args.workers) as pool:
            for file_path, reduced, err in pool.imap_unordered(worker_process, task_generator, chunksize=1):
                handle_result(file_path, reduced, err)

    if not found_any:
        print("No Python files found.")
        sys.exit(0)

    print("\n--- Summary ---")
    print(f"Successfully processed: {processed_count} file(s)")
    if error_count > 0:
        print(f"Errors encountered: {error_count} file(s)")
    print(f"Overall space freed: {format_bytes(total_space_freed, use_color)} bytes")


if __name__ == "__main__":
    mp.freeze_support()
    main()
