#!/data/data/com.termux/files/usr/bin/python
"""Copy-utility with optional Python mangling.
Usage:
  script.py <path> [start [end]] [-m|--mangle]
  script.py <path> -s <line> [<line> ...] [-m|--mangle]
Without -m,
content is copied as-is (whole file,
a range,
or an
explicit ordered selection).  With -m on a Python file (or a range
that parses as Python),
the code is stripped/mangled and a usage
prompt (TEXT1) is appended to the result.
"""

from __future__ import annotations
import ast
import builtins
from collections import Counter
from itertools import count, product
import keyword
from pathlib import Path
import string
import subprocess
import sys

TEXT1 = "Return full type-annotated code in one markdown block, no docstrings & no comments"
USAGE = """\
Usage: {prog} <path> [start [end]] [-m|--mangle]
       {prog} <path> -s <line> [<line> ...] [-m|--mangle]
  start/end  1-based inclusive line range (end defaults to last line)
  -s         copy only the listed lines, in the order given
  -m,--mangle
             compress Python code (strip docstrings/comments, shorten
             local names) and append a usage prompt.
Without -m, content is copied as-is."""
RESERVED = set(dir(builtins)) | set(keyword.kwlist)
SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
BLOCK_NODES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.ExceptHandler,
)


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def send_to_clipboard(text: str) -> bool:
    try:
        proc = subprocess.run(
            ["termux-clipboard-set"],
            input=text.encode("utf-8"),
            capture_output=True,
        )
    except FileNotFoundError:
        print(
            "Warning: 'termux-clipboard-set' not found; skipping clipboard copy. "
            "Install the Termux:API app and run: pkg install termux-api",
            file=sys.stderr,
        )
        return False
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        print(f"Warning: failed to copy to clipboard: {err}", file=sys.stderr)
        return False
    return True


# ---------- Step 1: strip comments, docstrings, annotations ----------
class Stripper(ast.NodeTransformer):
    def _drop_docstring(self, node) -> None:
        if node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                node.body = node.body[1:]

    def _scope(self, node):
        self._drop_docstring(node)
        return self.generic_visit(node)

    visit_Module = _scope
    visit_ClassDef = _scope

    def visit_FunctionDef(self, node):
        node.returns = None
        return self._scope(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_arg(self, node):
        node.annotation = None
        return node

    def visit_AnnAssign(self, node):
        if node.value is None:  # bare "x: int" declares nothing at runtime
            return None
        return ast.copy_location(ast.Assign(targets=[node.target], value=node.value), node)

    def visit_ImportFrom(self, node):
        if node.module == "__future__":
            return None
        return node


def _fill_empty_blocks(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, BLOCK_NODES) and not node.body:
            node.body = [ast.Pass()]


# ---------- Step 2: shorten identifiers ----------
def _all_identifiers(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, SCOPE_NODES):
            names.add(node.name)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.update(node.name.split("."))
            if node.asname:
                names.add(node.asname)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
    return names


def _unsafe_names(tree: ast.AST) -> set[str]:
    unsafe: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            unsafe.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            unsafe.add(node.arg)
        elif isinstance(node, ast.alias):
            unsafe.update(node.name.split("."))
            if node.asname:
                unsafe.add(node.asname)
        elif isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, SCOPE_NODES):
                    unsafe.add(stmt.name)
                elif isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        for n in ast.walk(target):
                            if isinstance(n, ast.Name):
                                unsafe.add(n.id)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            unsafe.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            unsafe.add(node.rest)
    return unsafe


def _name_stats(tree: ast.AST) -> tuple[set[str], Counter]:
    defined: set[str] = set()
    freq: Counter = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            freq[node.id] += 1
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                defined.add(node.id)
        elif isinstance(node, ast.arg):
            freq[node.arg] += 1
            defined.add(node.arg)
        elif isinstance(node, SCOPE_NODES):
            freq[node.name] += 1
            defined.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            freq[node.name] += 1
            defined.add(node.name)
    return defined, freq


def _short_names(taken: set[str]):
    for size in count(1):
        for chars in product(string.ascii_letters, repeat=size):
            name = "".join(chars)
            if name not in taken:
                yield name


class Renamer(ast.NodeTransformer):
    def __init__(self, mapping: dict[str, str]):
        self.m = mapping

    def _r(self, name: str) -> str:
        return self.m.get(name, name)

    def visit_Name(self, node):
        node.id = self._r(node.id)
        return node

    def visit_arg(self, node):
        node.arg = self._r(node.arg)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node):
        node.name = self._r(node.name)
        return self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        node.name = self._r(node.name)
        return self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        if node.name:
            node.name = self._r(node.name)
        return self.generic_visit(node)

    def visit_Global(self, node):
        node.names = [self._r(n) for n in node.names]
        return node

    visit_Nonlocal = visit_Global


def rename_identifiers(tree: ast.AST) -> ast.AST:
    defined, freq = _name_stats(tree)
    unsafe = _unsafe_names(tree)
    targets = [n for n in defined if n not in unsafe and n not in RESERVED and not n.startswith("__")]
    targets.sort(key=lambda n: (-freq[n], n))  # most-used names get shortest spellings
    taken = _all_identifiers(tree) | RESERVED | unsafe
    gen = _short_names(taken)
    mapping = {old: next(gen) for old in targets}
    return Renamer(mapping).visit(tree)


# ---------- Pipeline ----------
def _shrink_indent(code: str) -> str:
    out = []
    for line in code.splitlines():
        stripped = line.lstrip(" ")
        if stripped:
            out.append(" " * ((len(line) - len(stripped)) // 4) + stripped)
    return "\n".join(out) + "\n" if out else ""


def compress_source(source: str) -> str | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    tree = Stripper().visit(tree)
    _fill_empty_blocks(tree)
    tree = rename_identifiers(tree)
    code = _shrink_indent(ast.unparse(tree))
    try:
        compile(code, "<compressed>", "exec")  # sanity check before sending
    except SyntaxError:
        return None
    return code


def is_python_file(path: Path, source: str) -> bool:
    if path.suffix.lower() == ".py":
        return True
    if path.suffix == "":
        try:
            ast.parse(source)
            return True
        except (SyntaxError, ValueError):
            return False
    return False


def build_payload(path: Path, source: str, ranged: bool, mangle: bool) -> str:
    if not mangle:
        return source
    if ranged or is_python_file(path, source):
        compressed = compress_source(source)
        if compressed is not None:
            return compressed.rstrip("\n") + "\n\n" + TEXT1 + "\n"
        if ranged:
            print("Note: selection is not valid Python; copied as-is.", file=sys.stderr)
        else:
            print("Warning: could not parse file; copied as-is.", file=sys.stderr)
    return source


# ---------- CLI ----------
def main(argv: list[str]) -> None:
    raw = argv[1:]
    # Extract the mangling flag from anywhere on the command line.
    mangle = False
    rest: list[str] = []
    for a in raw:
        if a in ("-m", "--mangle"):
            mangle = True
        else:
            rest.append(a)
    args = [a for a in rest if a != "-s"]
    selective = len(args) != len(rest)
    if not args:
        die(USAGE.format(prog=Path(argv[0]).name))
    path = Path(args[0])
    if not path.is_file():
        die(f"Error: File not found at '{path}'")
    try:
        nums = [int(a) for a in args[1:]]
    except ValueError:
        die("Error: line numbers must be integers.")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        die(f"Error reading '{path}': {e}")
    lines = text.splitlines(keepends=True)
    total = len(lines)
    if selective:
        if not nums:
            die("Error: -s needs at least one line number.")
        bad = [n for n in nums if not 1 <= n <= total]
        if bad:
            die(f"Error: line(s) {bad} out of range. File has {total} lines.")
        source, ranged = "".join(lines[n - 1] for n in nums), True
    elif not nums:
        source, ranged = text, False
    elif len(nums) <= 2:
        start = nums[0]
        end = nums[1] if len(nums) == 2 else total
        if not 1 <= start <= total:
            die(f"Error: start line ({start}) out of range. File has {total} lines.")
        if not start <= end <= total:
            die(f"Error: end line ({end}) must be between start line and {total}.")
        source, ranged = "".join(lines[start - 1 : end]), True
    else:
        die(USAGE.format(prog=Path(argv[0]).name))
    if not source:
        die("No content selected to copy.")
    payload = build_payload(path, source, ranged, mangle)
    ok = send_to_clipboard(payload)
    status = "clipboard OK" if ok else "clipboard unavailable"
    print(
        f"Processed {len(payload)} chars (original {len(source)}); {status}.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
