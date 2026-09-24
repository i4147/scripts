import base64
import zlib
import ast
import builtins
import operator
import string
import sys
from pathlib import Path
from dh import cprint


PROTECTED_NAMES = set(dir(builtins)) | {
    "__file__",
    "__name__",
    "__doc__",
    "__main__",
    "self",
    "cls",
}

# ──────────────────── payload wrapping (zlib + b85) ──────────────────
STUB_TEMPLATE = """\
import base64 as _b, zlib as _z
exec(_z.decompress(_b.b85decode(_p)))
"""


def wrap_payload(source: str, *, level: int = 9) -> str:
    """Return a tiny runnable stub that exec()s the given source at runtime."""
    raw = source.encode("utf-8")
    packed = zlib.compress(raw, level)
    b85 = base64.b85encode(packed).decode("ascii")

    # Split b85 into fixed-width lines so the artifact stays readable & terminal-safe
    CHUNK = 100
    lines = [b85[i : i + CHUNK] for i in range(0, len(b85), CHUNK)]

    payload_literal = "_p=(" + "\n".join(f'"{ln}"' for ln in lines) + ")"

    return (
        f"# Compressed Python payload  "
        f"({len(raw)} -> {len(packed)} bytes zlib, "
        f"{len(b85)} base85 chars)\n"
        f"# Run with: python this_file.py\n"
        f"{STUB_TEMPLATE}\n"
        f"{payload_literal}\n"
    )


# ────────────────────────── stdlib discovery ──────────────────────────
def get_stdlib_modules():
    if hasattr(sys, "stdlib_module_names"):  # Python 3.10+
        return set(sys.stdlib_module_names)
    import sysconfig

    stdlib_path = Path(sysconfig.get_paths()["stdlib"])
    mods = set(sys.builtin_module_names)
    for entry in stdlib_path.iterdir():
        n = entry.name
        if n.endswith(".py"):
            mods.add(n[:-3])
        elif n.endswith(".so"):
            mods.add(n.split(".")[0])
        elif entry.is_dir():
            mods.add(n)
    return mods


STDLIB_MODULES = get_stdlib_modules()
STDLIB_KEEP = {"__future__"}


# ──────────────────── docstring + type stripping ──────────────────────
class StripDocstringsAndTypes(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        node.returns = None
        self._rm_doc(node)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        node.returns = None
        self._rm_doc(node)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        self._rm_doc(node)
        self.generic_visit(node)
        return node

    def visit_Module(self, node):
        self._rm_doc(node)
        self.generic_visit(node)
        return node

    def visit_arg(self, node):
        node.annotation = None
        return node

    def visit_AnnAssign(self, node):
        if node.value is None:
            return None
        new = ast.Assign(targets=[node.target], value=node.value)
        return self.generic_visit(new)

    @staticmethod
    def _rm_doc(node):
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)


# ────────────────────── stdlib import stripper ────────────────────────
class StdlibImportStripper(ast.NodeTransformer):
    def __init__(self):
        self.removed = []

    def visit_Import(self, node):
        kept = []
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in STDLIB_MODULES and top not in STDLIB_KEEP:
                text = f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                self.removed.append(text)
            else:
                kept.append(alias)
        if not kept:
            return None
        node.names = kept
        return node

    def visit_ImportFrom(self, node):
        if node.module is None:
            return node
        top = node.module.split(".")[0]
        if top in STDLIB_KEEP:
            return node
        if top in STDLIB_MODULES:
            for alias in node.names:
                if alias.asname:
                    self.removed.append(f"from {node.module} import {alias.name} as {alias.asname}")
                else:
                    self.removed.append(f"from {node.module} import {alias.name}")
            return None
        return node


# ─────────────────────── name shortening ──────────────────────────────
def generate_short_names():
    letters = string.ascii_lowercase
    idx = 0
    while True:
        yield letters[idx] if idx < 26 else f"{letters[idx % 26]}{idx // 26}"
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

    def _map(self, name):
        return self.name_map.get(name, name)

    def visit_FunctionDef(self, node):
        node.name = self._map(node.name)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        node.name = self._map(node.name)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        node.name = self._map(node.name)
        self.generic_visit(node)
        return node

    def visit_arg(self, node):
        node.arg = self._map(node.arg)
        return node

    def visit_Name(self, node):
        node.id = self._map(node.id)
        return node

    # ─── FIX #15: rename keyword-arg names too ───
    def visit_keyword(self, node):
        if node.arg is not None:
            node.arg = self._map(node.arg)
        return node


# ───────────────────────── peephole optimizer ─────────────────────────
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.BitAnd: operator.and_,
}
_UNARY_OPS = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Invert: operator.invert,
    ast.Not: operator.not_,
}
_AUG_OPS = frozenset(
    [
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.LShift,
        ast.RShift,
        ast.BitOr,
        ast.BitXor,
        ast.BitAnd,
        ast.MatMult,
    ]
)
_TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def _is_const(node, value):
    return isinstance(node, ast.Constant) and node.value is value


class PeepholeOptimizer(ast.NodeTransformer):
    """Semantics-preserving shrink passes (mostly AST-local)."""

    # ── statement-list level ──────────────────────────────────────────
    def generic_visit(self, node):
        super().generic_visit(node)
        for field in ("body", "orelse", "finalbody"):
            if hasattr(node, field):
                lst = getattr(node, field)
                if isinstance(lst, list) and lst and all(isinstance(x, ast.stmt) for x in lst):
                    setattr(node, field, self._optimize_stmts(lst))
        return node

    def _optimize_stmts(self, stmts):
        for _ in range(3):
            new = self._opt_pass(stmts)
            if len(new) == len(stmts) and all(a is b for a, b in zip(new, stmts)):
                break
            stmts = new
        return stmts

    def _opt_pass(self, stmts):
        # 5. Drop everything after a terminator (unreachable code)
        result = []
        for s in stmts:
            if result and isinstance(result[-1], _TERMINATORS):
                break
            result.append(s)

        # 3. `if c: body(terminates)\nelse: ...` → drop `else`
        flattened = []
        for s in result:
            if isinstance(s, ast.If) and s.orelse and s.body and isinstance(s.body[-1], _TERMINATORS):
                flattened.append(ast.If(test=s.test, body=s.body, orelse=[]))
                flattened.extend(s.orelse)
            else:
                flattened.append(s)
        result = flattened

        # 2. `if x: return True` / `return False` → `return bool(x)`
        out = []
        i = 0
        while i < len(result):
            s = result[i]
            if (
                i + 1 < len(result)
                and isinstance(s, ast.If)
                and not s.orelse
                and len(s.body) == 1
                and isinstance(s.body[0], ast.Return)
                and isinstance(result[i + 1], ast.Return)
            ):
                then_v = s.body[0].value
                else_v = result[i + 1].value
                if _is_const(then_v, True) and _is_const(else_v, False):
                    out.append(
                        ast.Return(value=ast.Call(func=ast.Name(id="bool", ctx=ast.Load()), args=[s.test], keywords=[]))
                    )
                    i += 2
                    continue
                if _is_const(then_v, False) and _is_const(else_v, True):
                    out.append(ast.Return(value=ast.UnaryOp(op=ast.Not(), operand=s.test)))
                    i += 2
                    continue
            out.append(s)
            i += 1
        return out

    # ── node level ────────────────────────────────────────────────────
    def visit_Assign(self, node):
        self.generic_visit(node)
        # 1. `x = x <op> y` → `x <op>= y`
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.BinOp)
            and isinstance(node.value.left, ast.Name)
            and node.targets[0].id == node.value.left.id
            and type(node.value.op) in _AUG_OPS
        ):
            return ast.copy_location(
                ast.AugAssign(target=node.targets[0], op=node.value.op, value=node.value.right), node
            )
        return node

    def visit_If(self, node):
        self.generic_visit(node)
        # 4. Merge nested ifs: `if a:\n if b: X`  →  `if a and b: X`
        if not node.orelse and len(node.body) == 1 and isinstance(node.body[0], ast.If) and not node.body[0].orelse:
            inner = node.body[0]
            return ast.copy_location(
                ast.If(test=ast.BoolOp(op=ast.And(), values=[node.test, inner.test]), body=inner.body, orelse=[]), node
            )
        # 8. `if True:` → `if 1:`, `if False:` → `if 0:`
        if isinstance(node.test, ast.Constant):
            if node.test.value is True:
                node.test = ast.copy_location(ast.Constant(value=1), node.test)
            elif node.test.value is False:
                node.test = ast.copy_location(ast.Constant(value=0), node.test)
        return node

    def visit_While(self, node):
        self.generic_visit(node)
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            node.test = ast.copy_location(ast.Constant(value=1), node.test)
        return node

    def visit_BinOp(self, node):
        self.generic_visit(node)
        # 7a. Constant-fold binary expressions
        if not (isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant)):
            return node
        op_fn = _BIN_OPS.get(type(node.op))
        if op_fn is None:
            return node
        if isinstance(node.op, (ast.Pow, ast.LShift)) and isinstance(node.right.value, int) and node.right.value > 64:
            return node  # avoid 2**10**9
        try:
            result = op_fn(node.left.value, node.right.value)
        except Exception:
            return node
        new = ast.Constant(value=result)
        try:
            if len(ast.unparse(new)) < len(ast.unparse(node)):
                return ast.copy_location(new, node)
        except Exception:
            pass
        return node

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        # 7b. Constant-fold unary expressions
        if not isinstance(node.operand, ast.Constant):
            return node
        op_fn = _UNARY_OPS.get(type(node.op))
        if op_fn is None:
            return node
        try:
            result = op_fn(node.operand.value)
        except Exception:
            return node
        new = ast.Constant(value=result)
        try:
            if len(ast.unparse(new)) < len(ast.unparse(node)):
                return ast.copy_location(new, node)
        except Exception:
            pass
        return node


# ──────────────────── semicolon-join post-processing ──────────────────
def _is_simple_line(line):
    s = line.strip()
    if not s or s.startswith("#") or s.endswith(":"):
        return False
    return True


def join_simple_lines(text):
    """Join consecutive simple statements at the same indent with `;`."""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if _is_simple_line(line):
            group = [stripped.rstrip()]
            j = i + 1
            while j < len(lines) and _is_simple_line(lines[j]):
                s2 = lines[j].lstrip()
                if lines[j][: len(lines[j]) - len(s2)] != indent:
                    break
                group.append(s2.rstrip())
                j += 1
            if len(group) > 1:
                out.append(indent + "; ".join(group))
                i = j
                continue
        out.append(line)
        i += 1
    return "\n".join(out)


# ───────────────────────────── driver ─────────────────────────────────
def compress_files(file_paths):
    name_map = {}
    name_gen = generate_short_names()
    parsed_trees = []
    removed_imports = []

    # First pass
    for filepath in file_paths:
        path = Path(filepath)
        if not path.exists():
            print(f"Warning: File '{filepath}' not found. Skipping.", file=sys.stderr)
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=filepath)

        tree = StripDocstringsAndTypes().visit(tree)
        ast.fix_missing_locations(tree)
        NameCollector(name_map, name_gen).visit(tree)

        stripper = StdlibImportStripper()
        tree = stripper.visit(tree)
        ast.fix_missing_locations(tree)
        removed_imports.extend(stripper.removed)

        parsed_trees.append((filepath, tree))

    # Second pass
    output_parts = []
    for filepath, tree in parsed_trees:
        tree = NameRenamer(name_map).visit(tree)
        ast.fix_missing_locations(tree)
        tree = PeepholeOptimizer().visit(tree)
        ast.fix_missing_locations(tree)

        minified = ast.unparse(tree)
        minified = join_simple_lines(minified)

        cleaned = [ln for ln in minified.splitlines() if ln.strip()]
        output_parts.append(f"# --- File: {filepath} ---\n" + "\n".join(cleaned))

    compressed = "\n\n".join(output_parts)

    if removed_imports:
        uniq = sorted(set(removed_imports))
        compressed += (
            "\n\n# --- NOTE: stdlib imports were stripped during compression ---\n"
            "# Re-add them (or ensure they are globally available) before running:\n"
            + "\n".join(f"#   {imp}" for imp in uniq)
        )

    Path("compressed.txt").write_text(compressed, encoding="utf-8")

    stub = wrap_payload(compressed)
    Path("compressed_stub.py").write_text(stub, encoding="utf-8")

    raw_sz = len(compressed.encode("utf-8"))
    stub_sz = len(stub.encode("utf-8"))
    ratio = raw_sz / stub_sz if stub_sz else 0
    cprint(
        f"Compressed {len(parsed_trees)} file(s); "
        f"removed {len(set(removed_imports))} stdlib import(s). "
        f"{raw_sz} -> {stub_sz} bytes ({ratio:.2f}x)."
    )


def get_python_files():
    return [str(p) for p in Path(".").rglob("*.py") if p.is_file()]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        files = get_python_files()
        if not files:
            print("No Python files found in current directory.")
            sys.exit(0)
        print(f"Processing {len(files)} Python files from current directory...")
        compress_files(files)
    else:
        compress_files(sys.argv[1:])
