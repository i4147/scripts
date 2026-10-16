#!/data/data/com.termux/files/usr/bin/python3.12
from __future__ import annotations

import argparse
import ast
import contextlib
import os
import re
import shutil
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

WORKERS = 8
LOGURU_LOGFORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} {level} {file.name}:{line} {message}"

MERGED_FILE_HEADER_RE = re.compile(r"^#\s*File:\s*(.+?)\s*$", re.MULTILINE)

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"

FG_BLACK = "\033[30m"
FG_RED = "\033[31m"
FG_GREEN = "\033[32m"
FG_YELLOW = "\033[33m"
FG_BLUE = "\033[34m"
FG_MAGENTA = "\033[35m"
FG_CYAN = "\033[36m"
FG_WHITE = "\033[37m"

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def visible_len(s: str) -> int:
    return len(_ANSI_RE.sub("", s))


def _fg256(n: int) -> str:
    return f"\033[38;5;{n}m"


class Style:
    def __init__(self) -> None:
        self.enabled = self._should_enable()
        self.unicode = self._supports_unicode()

    @staticmethod
    def _should_enable() -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("FORCE_COLOR"):
            return True
        return sys.stdout.isatty()

    @staticmethod
    def _supports_unicode() -> bool:
        enc = (sys.stdout.encoding or "").lower()
        return "utf" in enc

    def c(self, text: object, *codes: str) -> str:
        if not self.enabled or not codes:
            return str(text)
        return "".join(codes) + str(text) + RESET

    def bold(self, t: object) -> str:
        return self.c(t, BOLD)

    def dim(self, t: object) -> str:
        return self.c(t, DIM)

    def red(self, t: object) -> str:
        return self.c(t, BOLD, FG_RED)

    def green(self, t: object) -> str:
        return self.c(t, BOLD, FG_GREEN)

    def yellow(self, t: object) -> str:
        return self.c(t, BOLD, FG_YELLOW)

    def cyan(self, t: object) -> str:
        return self.c(t, BOLD, FG_CYAN)

    def magenta(self, t: object) -> str:
        return self.c(t, BOLD, FG_MAGENTA)

    def rainbow(self, text: object, i: int, total: int) -> str:
        if not self.enabled:
            return str(text)
        if total <= 1:
            n = 45
        else:
            t = i / max(1, total - 1)
            n = 21 + int(t * 30)
        return f"{_fg256(n)}{BOLD}{text}{RESET}"

    def colorize_path(self, path_str: str) -> str:
        if not self.enabled:
            return path_str
        if "/" in path_str:
            dir_part, _, name = path_str.rpartition("/")
            return self.c(dir_part + "/", DIM, FG_YELLOW) + self.c(name, BOLD, FG_CYAN)
        return self.c(path_str, BOLD, FG_CYAN)


def box(
    title: str,
    body_lines: list[str],
    style: Style,
    accent: str = FG_CYAN,
    width: Optional[int] = None,
) -> str:
    term = get_terminal_width()
    if width is None:
        width = max(44, min(term - 2, 84))
    if style.unicode:
        tl, tr, bl, br, h, v = "╭", "╮", "╰", "╯", "─", "│"
    else:
        tl, tr, bl, br, h, v = "+", "+", "+", "+", "-", "|"
    title_str = f" {title} "
    if visible_len(title_str) > width - 2:
        width = visible_len(title_str) + 2
    top = tl + title_str + h * (width - visible_len(title_str) - 2) + tr
    bottom = bl + h * (width - 2) + br
    out = [style.c(top, accent)]
    for line in body_lines:
        pad = " " * max(0, width - visible_len(line) - 4)
        out.append(style.c(v, accent) + " " + line + pad + " " + style.c(v, accent))
    out.append(style.c(bottom, accent))
    return "\n".join(out)


def banner(
    source_label: str,
    output: Path,
    module_count: int,
    style: Style,
) -> str:
    arrow = style.dim("→")
    lines = [
        f"{style.dim('source ')} {arrow} {style.colorize_path(source_label)}",
        f"{style.dim('output ')} {arrow} {style.colorize_path(str(output))}",
        f"{style.dim('files  ')} {arrow} {style.bold(module_count)}",
        f"{style.dim('workers')} {arrow} {style.bold(WORKERS)}",
    ]
    return box("refactor", lines, style, accent=FG_MAGENTA)


def success_box(output: Path, in_bytes: int, out_bytes: int, elapsed: float, style: Style) -> str:
    if style.unicode:
        check = "✓"
        warn = "⚠"
    else:
        check = "*"
        warn = "!"
    saved = in_bytes - out_bytes
    if in_bytes > 0:
        ratio = out_bytes / in_bytes
        if ratio >= 1:
            delta_str = style.yellow(f"+{saved * -1:,} B" if saved < 0 else f"{saved:,} B saved")
        else:
            delta_str = style.green(f"{abs(saved):,} B smaller ({ratio:.0%})")
    else:
        delta_str = style.dim("n/a")
    lines = [
        f"{style.green(check)} {style.bold('done')} in {style.cyan(f'{elapsed:.2f}s')}",
        f"{style.dim('in  ')} {in_bytes:>10,} B",
        f"{style.dim('out ')} {out_bytes:>10,} B   {delta_str}",
        f"{style.dim('file')} {style.colorize_path(str(output))}",
    ]
    return box("result", lines, style, accent=FG_GREEN)


def warning_box(items: list[tuple[str, int, str]], style: Style, verbose: bool) -> str:
    if style.unicode:
        mark = "⚠"
    else:
        mark = "!"
    header = f"{style.yellow(mark)} {style.bold(len(items))} parser warning(s) suppressed"
    lines = [
        header,
        style.dim("python 3.12+ flags invalid escape sequences in string literals"),
    ]
    shown = items if verbose else items[:5]
    for filename, lineno, message in shown:
        loc = style.colorize_path(filename) + style.dim(f":{lineno}")
        msg = style.c(message, DIM)
        lines.append(f"  {loc}  {msg}")
    if not verbose and len(items) > len(shown):
        lines.append(style.dim(f"  ... and {len(items) - len(shown)} more (use -v)"))
    return box("warnings", lines, style, accent=FG_YELLOW)


@dataclass
class ParseReport:
    items: list[tuple[str, int, str]] = field(default_factory=list)

    def extend_from(self, caught: list[warnings.WarningMessage]) -> None:
        for w in caught:
            if isinstance(
                w.message,
                (SyntaxWarning, DeprecationWarning, PendingDeprecationWarning),
            ):
                self.items.append((str(w.filename or "<unknown>"), int(w.lineno or 0), str(w.message)))

    def __bool__(self) -> bool:
        return bool(self.items)

    def __len__(self) -> int:
        return len(self.items)


@contextlib.contextmanager
def _collect_parse_warnings(report: ParseReport):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield
        finally:
            report.extend_from(caught)


def get_terminal_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:
        return default


def format_numbered_list(
    items: list[str],
    style: Style,
    indent: int = 2,
    min_gap: int = 4,
    max_gap: int = 16,
    min_fname: int = 12,
) -> str:
    items = [str(x) for x in items]
    if not items:
        return ""

    term = get_terminal_width()
    num_width = len(str(len(items)))
    prefix_w = indent + num_width + 2
    longest = max(len(s) for s in items)

    desired_gap = term - prefix_w - longest
    gap = max(min_gap, min(desired_gap, max_gap))

    avail = term - prefix_w - gap
    if avail < min_fname:
        avail = max(min_fname, term - prefix_w - min_gap)
        gap = max(min_gap, term - prefix_w - avail)

    total = len(items)
    lines: list[str] = []
    for i, s in enumerate(items):
        num = str(i + 1).rjust(num_width)
        num_colored = style.rainbow(num, i, total)
        display = s
        if len(display) > avail:
            keep = max(1, avail - 3)
            display = display[:keep] + "..."
        lines.append(f"{' ' * indent}{num_colored}{style.dim('.')}{' ' * gap}{style.colorize_path(display)}")
    return "\n".join(lines)


def collect_python_files(root: Path) -> list[Path]:
    if root.is_file():
        if root.suffix != ".py":
            raise SystemExit(f"{root} is not a .py file")
        return [root]
    files = [
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and not any(part.startswith(".") for part in p.parts)
    ]
    if not files:
        raise SystemExit(f"No .py files found under {root}")
    return sorted(files)


def parse_file(path: Path, report: ParseReport) -> ast.Module:
    src = path.read_text(encoding="utf-8")
    try:
        with _collect_parse_warnings(report):
            return ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        raise SystemExit(f"Syntax error in {path}: {exc}")


def parse_merged_file(path: Path, report: ParseReport) -> list[tuple[str, ast.Module]]:
    text = path.read_text(encoding="utf-8")
    matches = list(MERGED_FILE_HEADER_RE.finditer(text))
    if not matches:
        raise SystemExit(
            f"No '# File: <path>' headers found in {path}; "
            "expected a merged file such as:\n"
            "  # File: __init__.py\n"
            "  ...\n"
            "  # File: sub/mod.py\n"
            "  ...\n"
            "Use directory mode instead if you have loose .py files."
        )
    modules: list[tuple[str, ast.Module]] = []
    for i, m in enumerate(matches):
        header_path = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        if body.startswith("\r\n"):
            body = body[2:]
        elif body.startswith("\n"):
            body = body[1:]
        try:
            with _collect_parse_warnings(report):
                tree = ast.parse(body, filename=header_path)
        except SyntaxError as exc:
            raise SystemExit(f"Syntax error in {path} section '{header_path}': {exc}")
        modules.append((header_path, tree))
    return modules


def is_relative_import(node: ast.AST) -> bool:
    return isinstance(node, ast.ImportFrom) and bool(node.level)


def is_future_import(node: ast.AST) -> bool:
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def is_six_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(a.name == "six" or a.name.startswith("six.") for a in node.names)
    if isinstance(node, ast.ImportFrom):
        m = node.module or ""
        return m == "six" or m.startswith("six.")
    return False


def is_logging_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(a.name == "logging" for a in node.names)
    if isinstance(node, ast.ImportFrom):
        m = node.module or ""
        return m == "logging" or m.startswith("logging.")
    return False


def _is_named_assign(node: ast.AST, name: str) -> bool:
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    )


def _make_assign(name: str, value: ast.expr) -> ast.Assign:
    return ast.Assign(targets=[ast.Name(id=name, ctx=ast.Store())], value=value)


def _module_has_import_from_src(module: ast.Module, src_fragment: str) -> bool:
    target = src_fragment.strip()
    for node in module.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            try:
                if ast.unparse(node).strip() == target:
                    return True
            except Exception:
                continue
    return False


def merge_modules(modules: list[tuple[str, ast.Module]]) -> list[ast.stmt]:
    merged: list[ast.stmt] = []
    seen_imports: set[str] = set()
    for _name, tree in modules:
        for node in tree.body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                continue
            if is_future_import(node):
                continue
            if is_six_import(node) or is_logging_import(node):
                continue
            if is_relative_import(node):
                continue
            if _is_named_assign(node, "__all__"):
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                key = ast.dump(node)
                if key in seen_imports:
                    continue
                seen_imports.add(key)
            merged.append(node)
    return merged


SIX_ATTR_MAP: dict[str, str] = {
    "text_type": "str",
    "binary_type": "bytes",
    "class_types": "type",
    "integer_types": "int",
    "string_types": "str",
}

SIX_MOVES_MAP: dict[str, str] = {
    "six.moves.urllib.request": "urllib.request",
    "six.moves.urllib.error": "urllib.error",
    "six.moves.urllib.parse": "urllib.parse",
    "six.moves.urllib.response": "urllib.response",
    "six.moves.urllib": "urllib",
    "six.moves.http_client": "http.client",
    "six.moves.cPickle": "pickle",
    "six.moves.copyreg": "copyreg",
    "six.moves.queue": "queue",
    "six.moves.range": "builtins",
    "six.moves.map": "builtins",
    "six.moves.zip": "builtins",
    "six.moves.input": "builtins",
    "six.moves": "builtins",
}


class SixImportRewriter(ast.NodeTransformer):
    def visit_ImportFrom(self, node: ast.ImportFrom) -> Optional[ast.AST]:
        self.generic_visit(node)
        m = node.module or ""
        if m in SIX_MOVES_MAP:
            mapped = SIX_MOVES_MAP[m]
            if mapped == "builtins":
                return None
            node.module = mapped
            return node
        if m == "six":
            return None
        return node

    def visit_Import(self, node: ast.Import) -> Optional[ast.AST]:
        self.generic_visit(node)
        kept = [a for a in node.names if a.name != "six"]
        if not kept:
            return None
        node.names = kept
        return node


class SixTransformer(ast.NodeTransformer):
    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == "six":
            if node.attr == "PY2":
                return ast.Constant(value=False)
            if node.attr == "PY3":
                return ast.Constant(value=True)
            if node.attr in SIX_ATTR_MAP:
                return ast.Name(id=SIX_ATTR_MAP[node.attr], ctx=node.ctx)
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        func = node.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "six"):
            return node
        method = func.attr
        if method in ("iteritems", "iterkeys", "itervalues") and len(node.args) == 1:
            mapped = {"iteritems": "items", "iterkeys": "keys", "itervalues": "values"}[method]
            return ast.Call(
                func=ast.Attribute(value=node.args[0], attr=mapped, ctx=ast.Load()),
                args=[],
                keywords=[],
            )
        if method == "u" and len(node.args) == 1:
            return node.args[0]
        if method == "string_types" and not node.args:
            return ast.Name(id="str", ctx=ast.Load())
        return node


OSPATH_PROPERTY_MAP: dict[str, str] = {
    "exists": "exists",
    "isdir": "is_dir",
    "isfile": "is_file",
    "islink": "is_symlink",
    "dirname": "parent",
    "basename": "name",
}

OSPATH_METHOD_MAP: dict[str, str] = {
    "abspath": "resolve",
    "realpath": "resolve",
    "expanduser": "expanduser",
    "remove": "unlink",
    "unlink": "unlink",
    "stat": "stat",
    "mkdir": "mkdir",
}

OSPATH_MAKEDIRS = "makedirs"
OSPATH_GETSIZE = "getsize"


def _wrap_path(arg: ast.expr) -> ast.Call:
    return ast.Call(func=ast.Name(id="Path", ctx=ast.Load()), args=[arg], keywords=[])


class OsPathTransformer(ast.NodeTransformer):
    def __init__(self, bare_path: bool = False) -> None:
        super().__init__()
        self.bare_path = bare_path

    def _is_ospath(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "os" and node.attr == "path":
                return True
            if self.bare_path and node.value.id == "path":
                return True
        return False

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        func = node.func
        if not isinstance(func, ast.Attribute) or not self._is_ospath(func.value):
            return node
        method = func.attr
        args = node.args

        if method == "join" and len(args) >= 1:
            base = _wrap_path(args[0])
            if len(args) == 1:
                return base
            return ast.Call(
                func=ast.Attribute(value=base, attr="joinpath", ctx=ast.Load()),
                args=list(args[1:]),
                keywords=[],
            )

        if method in OSPATH_PROPERTY_MAP and len(args) == 1:
            return ast.Attribute(
                value=_wrap_path(args[0]),
                attr=OSPATH_PROPERTY_MAP[method],
                ctx=ast.Load(),
            )

        if method in OSPATH_METHOD_MAP and len(args) == 1:
            return ast.Call(
                func=ast.Attribute(
                    value=_wrap_path(args[0]),
                    attr=OSPATH_METHOD_MAP[method],
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )

        if method == OSPATH_MAKEDIRS and len(args) == 1:
            return ast.Call(
                func=ast.Attribute(value=_wrap_path(args[0]), attr="mkdir", ctx=ast.Load()),
                args=[],
                keywords=[ast.keyword(arg="parents", value=ast.Constant(value=True))],
            )

        if method == OSPATH_GETSIZE and len(args) == 1:
            stat_call = ast.Call(
                func=ast.Attribute(value=_wrap_path(args[0]), attr="stat", ctx=ast.Load()),
                args=[],
                keywords=[],
            )
            return ast.Attribute(value=stat_call, attr="st_size", ctx=ast.Load())

        return node

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        self.generic_visit(node)
        slice_ = node.slice
        if not (isinstance(slice_, ast.Constant) and slice_.value == 1):
            return node
        call = node.value
        if not (isinstance(call, ast.Call) and len(call.args) == 1):
            return node
        if not (
            isinstance(call.func, ast.Attribute) and call.func.attr == "splitext" and self._is_ospath(call.func.value)
        ):
            return node
        return ast.Attribute(
            value=_wrap_path(call.args[0]),
            attr="suffix",
            ctx=ast.Load(),
        )


_EXECUTOR_NAMES = {"ProcessPoolExecutor", "ThreadPoolExecutor"}


class _ExecutorMethodRenamer(ast.NodeTransformer):
    def __init__(self, var: str) -> None:
        super().__init__()
        self.var = var

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        f = node.func
        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == self.var
            and f.attr == "map"
        ):
            f.attr = "imap_unordered"
            f.value = ast.Name(id="_pool", ctx=ast.Load())
        return node


def _is_executor_ref(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _EXECUTOR_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in _EXECUTOR_NAMES
    return False


class ExecutorTransformer(ast.NodeTransformer):
    def visit_With(self, node: ast.With) -> ast.AST:
        self.generic_visit(node)
        if len(node.items) != 1:
            return node
        item = node.items[0]
        ctx = item.context_expr
        if not (isinstance(ctx, ast.Call) and _is_executor_ref(ctx.func)):
            return node
        var = item.optional_vars
        if not isinstance(var, ast.Name):
            return node

        pool_assign = ast.Assign(
            targets=[ast.Name(id="_pool", ctx=ast.Store())],
            value=ast.Call(
                func=ast.Attribute(value=ast.Name(id="mp", ctx=ast.Load()), attr="Pool", ctx=ast.Load()),
                args=[ast.Name(id="WORKERS", ctx=ast.Load())],
                keywords=[],
            ),
        )

        renamer = _ExecutorMethodRenamer(var.id)
        new_body = [renamer.visit(stmt) for stmt in node.body]

        cleanup = [
            ast.Expr(
                ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="_pool", ctx=ast.Load()),
                        attr="close",
                        ctx=ast.Load(),
                    ),
                    args=[],
                    keywords=[],
                )
            ),
            ast.Expr(
                ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="_pool", ctx=ast.Load()),
                        attr="join",
                        ctx=ast.Load(),
                    ),
                    args=[],
                    keywords=[],
                )
            ),
        ]

        try_node = ast.Try(body=new_body, handlers=[], orelse=[], finalbody=cleanup)
        return [pool_assign, try_node]


class LoggingTransformer(ast.NodeTransformer):
    def visit_Assign(self, node: ast.Assign) -> Optional[ast.AST]:
        self.generic_visit(node)
        v = node.value
        if (
            isinstance(v, ast.Call)
            and isinstance(v.func, ast.Attribute)
            and isinstance(v.func.value, ast.Name)
            and v.func.value.id == "logging"
            and v.func.attr == "getLogger"
        ):
            return None
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == "logging":
            if node.attr.isupper():
                return ast.Constant(value=node.attr)
        return node

    def visit_Expr(self, node: ast.Expr) -> ast.AST:
        self.generic_visit(node)
        call = node.value
        if not isinstance(call, ast.Call):
            return node
        f = call.func

        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "logging"
            and f.attr == "basicConfig"
        ):
            fmt = ast.Constant(value=LOGURU_LOGFORMAT)
            for kw in call.keywords:
                if kw.arg == "format":
                    fmt = kw.value
                    break
            return [
                ast.Expr(
                    ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="logger", ctx=ast.Load()),
                            attr="remove",
                            ctx=ast.Load(),
                        ),
                        args=[],
                        keywords=[],
                    )
                ),
                ast.Expr(
                    ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="logger", ctx=ast.Load()),
                            attr="add",
                            ctx=ast.Load(),
                        ),
                        args=[
                            ast.Attribute(
                                value=ast.Name(id="sys", ctx=ast.Load()),
                                attr="stderr",
                                ctx=ast.Load(),
                            )
                        ],
                        keywords=[ast.keyword(arg="format", value=fmt)],
                    )
                ),
            ]

        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "logger"
            and f.attr == "setLevel"
            and call.args
        ):
            return ast.Expr(
                ast.Call(
                    func=ast.Attribute(
                        value=ast.Name(id="logger", ctx=ast.Load()),
                        attr="add",
                        ctx=ast.Load(),
                    ),
                    args=[
                        ast.Attribute(
                            value=ast.Name(id="sys", ctx=ast.Load()),
                            attr="stderr",
                            ctx=ast.Load(),
                        )
                    ],
                    keywords=[ast.keyword(arg="level", value=call.args[0])],
                )
            )

        return node


_DEF_NODES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def strip_docstrings(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, _DEF_NODES):
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]


_STANDARD_HEADER = [
    "import sys",
    "import multiprocessing as mp",
    "from pathlib import Path",
    "from loguru import logger",
]


def inject_standard_imports(module: ast.Module) -> ast.Module:
    prefix: list[ast.stmt] = []
    for line in _STANDARD_HEADER:
        if not _module_has_import_from_src(module, line):
            prefix.extend(ast.parse(line).body)
    module.body = prefix + module.body
    return module


def _module_imports_path_bare(module: ast.Module) -> bool:
    for node in module.body:
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            for a in node.names:
                if a.name == "path":
                    return True
    return False


def _sum_input_bytes(modules: list[tuple[str, ast.Module]]) -> int:
    total = 0
    for name, _tree in modules:
        p = Path(name)
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def refactor(
    modules: list[tuple[str, ast.Module]],
    output: Path,
    source_label: str,
    style: Style,
    quiet: bool = False,
    verbose: bool = False,
    parse_report: Optional[ParseReport] = None,
) -> None:
    t0 = time.perf_counter()

    if not quiet:
        print(banner(source_label, output, len(modules), style))
        print()
        names = [name for name, _ in modules]
        print(f"{style.dim('merging')} {style.bold(len(names))} {style.dim('module(s)')}:")
        print()
        print(format_numbered_list(names, style))
        print()
        if parse_report:
            print(warning_box(parse_report.items, style, verbose))
            print()

    in_bytes = _sum_input_bytes(modules)

    merged = merge_modules(modules)
    module = ast.Module(body=merged, type_ignores=[])

    bare_path = _module_imports_path_bare(module)

    for T in (SixImportRewriter, SixTransformer, LoggingTransformer):
        module = T().visit(module)
    module = OsPathTransformer(bare_path=bare_path).visit(module)
    module = ExecutorTransformer().visit(module)

    module.body = [n for n in module.body if not _is_named_assign(n, "WORKERS")]
    module.body.insert(0, _make_assign("WORKERS", ast.Constant(value=WORKERS)))

    module = inject_standard_imports(module)

    strip_docstrings(module)
    ast.fix_missing_locations(module)

    src = ast.unparse(module)
    src = re.sub(r"\n{3,}", "\n\n\n", src)

    try:
        ast.parse(src)
    except SyntaxError as exc:
        check_path = output.with_suffix(".check.py")
        check_path.write_text(src + "\n", encoding="utf-8")
        raise SystemExit(
            f"Generated code failed to parse: {exc}\nPartial output written to {check_path} for manual fixing."
        )

    output.write_text(src + "\n", encoding="utf-8")
    out_bytes = output.stat().st_size
    elapsed = time.perf_counter() - t0

    if not quiet:
        print(success_box(output, in_bytes, out_bytes, elapsed, style))
        print()
        print(style.dim("note: PEP 484 annotations were preserved but not inferred; add missing ones by hand."))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Consolidate a multi-file Python package into one module.")
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=None,
        help="package directory or .py file (default: current directory)",
    )
    parser.add_argument(
        "-f",
        "--merged-file",
        type=Path,
        default=None,
        help="read source from a single merged file containing '# File: <path>' section headers",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="output file (default: <source_name>_single.py in cwd)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="suppress all chrome; write the file only",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="show every parser warning (default: cap at 5)",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="disable ANSI colors (also honors NO_COLOR env var)",
    )
    args = parser.parse_args(argv)

    if args.no_color:
        os.environ["NO_COLOR"] = "1"

    style = Style()

    if args.merged_file is not None and args.input is not None:
        raise SystemExit("Provide either a positional INPUT or -f/--merged-file, not both")

    parse_report = ParseReport()

    if args.merged_file is not None:
        merged_path: Path = args.merged_file
        if not merged_path.exists():
            raise SystemExit(f"{merged_path} does not exist")
        if not merged_path.is_file():
            raise SystemExit(f"{merged_path} is not a file")
        modules = parse_merged_file(merged_path, parse_report)
        source_label = str(merged_path)
        source_default = merged_path.stem
    else:
        input_path: Path = args.input if args.input is not None else Path(".")
        if not input_path.exists():
            raise SystemExit(f"{input_path} does not exist")
        files = collect_python_files(input_path)
        modules = [(str(p), parse_file(p, parse_report)) for p in files]
        source_label = str(input_path)
        source_default = input_path.stem if input_path.is_file() else input_path.name

    output: Optional[Path] = args.output
    if output is None:
        output = Path.cwd() / f"{source_default}_single.py"

    if args.merged_file is not None and output.resolve() == args.merged_file.resolve():
        raise SystemExit("Refusing to overwrite the input merged file")
    if args.input is not None and output.resolve() == args.input.resolve():
        raise SystemExit("Refusing to overwrite the input path")

    refactor(
        modules,
        output,
        source_label,
        style,
        quiet=args.quiet,
        verbose=args.verbose,
        parse_report=parse_report,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
