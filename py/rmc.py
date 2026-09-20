
import ast
import sys
import os
from pathlib import Path
import argparse
import io
import tokenize
from typing import List, Tuple, Optional
from dh import has_doc, get_pyfiles, cprint, mpf3


def get_offset_map(source: str) -> List[int]:
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def offset_from_pos(lineno: int, col_offset: int, line_offsets: List[int]) -> int:
    return line_offsets[lineno - 1] + col_offset




RawAction = Tuple[int, int, int, int, Optional[str]]


def gather_docstring_actions(tree: ast.AST) -> List[RawAction]:

    actions: List[RawAction] = []
    module_doc = None
    if (
        isinstance(tree, ast.Module)
        and tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        module_doc = tree.body[0]

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.body:
                continue
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                if first is module_doc:
                    continue
                is_only = len(node.body) == 1
                replacement = "pass" if is_only else None
                actions.append((first.lineno, first.col_offset, first.end_lineno, first.end_col_offset, replacement))
    return actions


def gather_comment_actions(source: str) -> List[RawAction]:

    actions: List[RawAction] = []
    line_offsets = get_offset_map(source)
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                start_line, start_col = tok.start
                end_line, end_col = tok.end
                
                start = offset_from_pos(start_line, start_col, line_offsets)
                end = offset_from_pos(end_line, end_col, line_offsets)
                
                if end > start and source[end - 1] == "\n":
                    end -= 1
                actions.append((start_line, start_col, end_line, end_col, None))
    except tokenize.TokenError:
        pass  
    return actions


def apply_actions(source: str, raw_actions: List[RawAction]) -> str:

    if not raw_actions:
        return source

    line_offsets = get_offset_map(source)

    
    abs_actions = []
    for sl, sc, el, ec, repl in raw_actions:
        start = offset_from_pos(sl, sc, line_offsets)
        end = offset_from_pos(el, ec, line_offsets)
        abs_actions.append((start, end, repl))

    
    abs_actions.sort(key=lambda a: a[0], reverse=True)

    for start, end, repl in abs_actions:
        if repl is None:
            
            source = source[:start] + source[end:]
        else:
            
            source = source[:start] + repl + source[end:]

    return source


def process_file(path: str | Path, remove_comments: bool) -> str:
    path = Path(path)
    try:
        code = path.read_text(encoding="utf-8")
        if not has_doc(code):
            return

        tree = ast.parse(code, filename=path)
        actions = gather_docstring_actions(tree)

        if remove_comments:
            comment_actions = gather_comment_actions(code)
            actions.extend(comment_actions)

        if not actions:
            cprint(f"{path.name}: (no change)", "grey")
            return

        new_source = apply_actions(code, actions)

        if new_source == code:
            cprint(f"{path.name}: no changes", "grey")
            return

        
        try:
            ast.parse(new_source, filename=path)
        except SyntaxError as ve:
            print(f"{path.name}: validation failed – not written. SyntaxError: {ve}")

            path.write_text(new_source, encoding="utf-8")

        
        docstring_actions = [a for a in actions if a in gather_docstring_actions(tree)]
        sole_replaced = sum(1 for a in docstring_actions if a[4] == "pass")
        doc_removed = len(docstring_actions) - sole_replaced
        comment_removed = len(actions) - len(docstring_actions)

        msg_parts = []
        if doc_removed:
            msg_parts.append(f"removed {doc_removed} docstring(s)")
        if sole_replaced:
            msg_parts.append(f"replaced {sole_replaced} sole docstring(s) with pass")
        if comment_removed:
            msg_parts.append(f"removed {comment_removed} comment(s)")

        print(f"{path.name}: " + ", ".join(msg_parts))

    except SyntaxError as e:
        print(f"{path.name}: original file syntax error – {e}")
        return
    except Exception as e:
        print(f"{path.name}: unexpected error – {e}")
        return


def find_py_files(root: str) -> List[str]:
    return get_pyfiles(root)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove docstrings and/or comments from Python files (preserving module docstring)."
    )
    parser.add_argument(
        "path", nargs="?", default=None, help="A Python file or a directory. Defaults to current directory."
    )
    args = parser.parse_args()

    if args.path is None:
        target = os.getcwd()
    else:
        target = os.path.abspath(args.path)

    if os.path.isfile(target):
        py_files = [target]
    elif os.path.isdir(target):
        py_files = find_py_files(target)
    else:
        print(f"Error: '{target}' is not a valid file or directory.", file=sys.stderr)
        sys.exit(1)

    if not py_files:
        print("No Python files found.")
        return

    workers = 6
    mode = "docstrings and comments"

    from functools import partial

    worker = partial(process_file, remove_comments=args.remove_comments)

    mpf3(worker, py_files)


if __name__ == "__main__":
    main()
