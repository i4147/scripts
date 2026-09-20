from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import sys
import textwrap
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

STDLIB_MODULES = set(sys.builtin_module_names)
for module_name in list(sys.modules.keys()):
    if hasattr(importlib.util, "find_spec"):
        try:
            spec = importlib.util.find_spec(module_name)
            if spec and spec.origin and ("site-packages" not in spec.origin):
                STDLIB_MODULES.add(module_name.split(".")[0])
        except (ImportError, ModuleNotFoundError, ValueError):
            pass


class ImportAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.imported_names: set[str] = set()
        self.used_names: set[str] = set()
        self.assigned_names: set[str] = set()
        self.import_lines: dict[str, int] = {}
        self.builtin_names: set[str] = {
            "print",
            "len",
            "range",
            "str",
            "int",
            "float",
            "list",
            "dict",
            "set",
            "tuple",
            "bool",
            "bytes",
            "bytearray",
            "object",
            "type",
            "super",
            "property",
            "classmethod",
            "staticmethod",
            "open",
            "input",
            "enumerate",
            "zip",
            "map",
            "filter",
            "sorted",
            "reversed",
            "sum",
            "min",
            "max",
            "all",
            "any",
            "abs",
            "round",
            "pow",
            "divmod",
            "hex",
            "oct",
            "bin",
            "ord",
            "chr",
            "ascii",
            "repr",
            "format",
            "hash",
            "id",
            "isinstance",
            "issubclass",
            "callable",
            "iter",
            "next",
            "compile",
            "eval",
            "exec",
            "globals",
            "locals",
            "vars",
            "dir",
            "help",
            "getattr",
            "setattr",
            "delattr",
            "hasattr",
            "Exception",
            "BaseException",
            "ValueError",
            "TypeError",
            "RuntimeError",
            "KeyError",
            "IndexError",
            "AttributeError",
            "NameError",
            "IOError",
            "OSError",
            "ImportError",
            "ModuleNotFoundError",
            "StopIteration",
            "GeneratorExit",
            "KeyboardInterrupt",
            "SystemExit",
            "NotImplemented",
            "Ellipsis",
            "None",
            "True",
            "False",
            "__name__",
            "__doc__",
            "__package__",
            "__file__",
            "__cached__",
            "__loader__",
            "__spec__",
        }

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            base_name = alias.name.split(".")[0]
            self.imported_names.add(base_name)
            self.import_lines[base_name] = node.lineno
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            base_name = node.module.split(".")[0]
            self.imported_names.add(base_name)
            self.import_lines[base_name] = node.lineno
        for alias in node.names:
            if alias.name != "*":
                self.imported_names.add(alias.name)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.assigned_names.add(target.id)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for elt in ast.walk(target):
                    if isinstance(elt, ast.Name):
                        self.assigned_names.add(elt.id)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            self.assigned_names.add(node.target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self.assigned_names.add(node.target.id)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        if isinstance(node.target, ast.Name):
            self.assigned_names.add(node.target.id)
        elif isinstance(node.target, (ast.Tuple, ast.List)):
            for elt in ast.walk(node.target):
                if isinstance(elt, ast.Name):
                    self.assigned_names.add(elt.id)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars:
                if isinstance(item.optional_vars, ast.Name):
                    self.assigned_names.add(item.optional_vars.id)
                elif isinstance(item.optional_vars, (ast.Tuple, ast.List)):
                    for elt in ast.walk(item.optional_vars):
                        if isinstance(elt, ast.Name):
                            self.assigned_names.add(elt.id)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.assigned_names.add(node.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.assigned_names.add(node.name)
        for arg in node.args.args:
            self.assigned_names.add(arg.arg)
        if node.args.vararg:
            self.assigned_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            self.assigned_names.add(node.args.kwarg.arg)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.assigned_names.add(node.name)
        for arg in node.args.args:
            self.assigned_names.add(arg.arg)
        if node.args.vararg:
            self.assigned_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            self.assigned_names.add(node.args.kwarg.arg)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.assigned_names.add(node.name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name):
            self.used_names.add(node.value.id)
        self.generic_visit(node)


def get_stdlib_modules() -> set[str]:
    stdlib = set(sys.builtin_module_names)
    common_stdlib = {
        "abc",
        "argparse",
        "array",
        "asyncio",
        "base64",
        "bisect",
        "builtins",
        "bz2",
        "calendar",
        "cmath",
        "cmd",
        "code",
        "codecs",
        "codeop",
        "collections",
        "colorsys",
        "compileall",
        "concurrent",
        "configparser",
        "contextlib",
        "copy",
        "copyreg",
        "cProfile",
        "csv",
        "ctypes",
        "curses",
        "dataclasses",
        "datetime",
        "dbm",
        "decimal",
        "difflib",
        "dis",
        "doctest",
        "email",
        "encodings",
        "ensurepip",
        "enum",
        "errno",
        "faulthandler",
        "fcntl",
        "filecmp",
        "fileinput",
        "fnmatch",
        "fractions",
        "ftplib",
        "functools",
        "gc",
        "getopt",
        "getpass",
        "gettext",
        "glob",
        "grp",
        "gzip",
        "hashlib",
        "heapq",
        "hmac",
        "html",
        "http",
        "imaplib",
        "imghdr",
        "imp",
        "importlib",
        "inspect",
        "io",
        "ipaddress",
        "itertools",
        "json",
        "keyword",
        "lib2to3",
        "linecache",
        "locale",
        "logging",
        "lzma",
        "mailbox",
        "mailcap",
        "marshal",
        "math",
        "mimetypes",
        "mmap",
        "modulefinder",
        "msilib",
        "msvcrt",
        "multiprocessing",
        "netrc",
        "nis",
        "nntplib",
        "numbers",
        "operator",
        "optparse",
        "os",
        "ossaudiodev",
        "parser",
        "pathlib",
        "pdb",
        "pickle",
        "pickletools",
        "pipes",
        "pkgutil",
        "platform",
        "plistlib",
        "poplib",
        "posix",
        "posixpath",
        "pprint",
        "profile",
        "pstats",
        "pty",
        "pwd",
        "py_compile",
        "pyclbr",
        "pydoc",
        "queue",
        "quopri",
        "random",
        "re",
        "readline",
        "reprlib",
        "resource",
        "rlcompleter",
        "runpy",
        "sched",
        "secrets",
        "select",
        "selectors",
        "shelve",
        "shlex",
        "shutil",
        "signal",
        "site",
        "smtpd",
        "smtplib",
        "sndhdr",
        "socket",
        "socketserver",
        "spwd",
        "sqlite3",
        "ssl",
        "stat",
        "statistics",
        "string",
        "stringprep",
        "struct",
        "subprocess",
        "sunau",
        "symbol",
        "symtable",
        "sys",
        "sysconfig",
        "syslog",
        "tabnanny",
        "tarfile",
        "telnetlib",
        "tempfile",
        "termios",
        "test",
        "textwrap",
        "threading",
        "time",
        "timeit",
        "tkinter",
        "token",
        "tokenize",
        "trace",
        "traceback",
        "tracemalloc",
        "tty",
        "turtle",
        "turtledemo",
        "types",
        "typing",
        "typing_extensions",
        "unicodedata",
        "unittest",
        "urllib",
        "uu",
        "uuid",
        "venv",
        "warnings",
        "wave",
        "weakref",
        "webbrowser",
        "winreg",
        "winsound",
        "wsgiref",
        "xdrlib",
        "xml",
        "xmlrpc",
        "zipapp",
        "zipfile",
        "zipimport",
        "zlib",
        "zoneinfo",
    }
    stdlib.update(common_stdlib)
    return stdlib


def analyze_file(filepath: Path) -> tuple[Path, list[tuple[str, int]]]:
    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content, str(filepath))
        analyzer = ImportAnalyzer()
        analyzer.visit(tree)
        stdlib = get_stdlib_modules()
        missing_imports = []
        for name in analyzer.used_names:
            if (
                name not in analyzer.imported_names
                and name not in analyzer.assigned_names
                and (name not in analyzer.builtin_names)
                and (name in stdlib)
                and (not name.startswith("_"))
            ):
                line_num = 0
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name) and node.id == name:
                        line_num = node.lineno
                        break
                missing_imports.append((name, line_num or 1))
        return (filepath, missing_imports)
    except (SyntaxError, UnicodeDecodeError):
        return (filepath, [])


def autofix_imports(filepath: Path, missing_imports: list[tuple[str, int]]) -> bool:
    if not missing_imports:
        return False
    try:
        with open(filepath, encoding="utf-8") as f:
            lines = f.readlines()
        unique_imports = sorted({imp[0] for imp in missing_imports})
        insert_idx = 0
        in_imports = True
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(("import ", "from ")):
                insert_idx = i + 1
            elif in_imports and (not stripped.startswith(("import ", "from "))):
                in_imports = False
        new_imports = [f"import {imp}\n" for imp in unique_imports]
        lines[insert_idx:insert_idx] = new_imports
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Find and fix missing stdlib imports in Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            "\n            Examples:\n              python find_missing_imports.py\n              python find_missing_imports.py --autofix\n              python find_missing_imports.py --workers 8\n        "
        ),
    )
    parser.add_argument("-a", "--autofix", action="store_true", help="Automatically add missing imports")
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes (default: CPU count)",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    args = parser.parse_args()
    root_dir = Path(args.directory).resolve()
    if not root_dir.is_dir():
        print(f"Error: {root_dir} is not a directory")
        sys.exit(1)
    py_files = list(root_dir.glob("**/*.py"))
    if not py_files:
        print(f"No Python files found in {root_dir}")
        sys.exit(0)
    print(f"Scanning {len(py_files)} Python files with {args.workers or 'default'} workers...")
    total_missing = 0
    fixed_files = 0
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(analyze_file, py_file): py_file for py_file in py_files}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            filepath, missing_imports = future.result()
            pct = completed / len(py_files) * 40
            print(f"[{pct:5.1f}%] {completed}/{len(py_files)}", end="\r", flush=True)
            if missing_imports:
                total_missing += len(missing_imports)
                rel_path = filepath.relative_to(root_dir)
                print(f"\n{rel_path}:")
                for module, lineno in sorted(set(missing_imports)):
                    print(f"  Line {lineno}: missing `import {module}`")
                if args.autofix:
                    if autofix_imports(filepath, missing_imports):
                        print("  ✓ Fixed")
                        fixed_files += 1
                    else:
                        print("  ✗ Failed to fix")
    print(f"\n{'─' * 40}")
    print(f"Total missing imports found: {total_missing}")
    if args.autofix:
        print(f"Files fixed: {fixed_files}")
    sys.exit(1 if total_missing > 0 else 0)


if __name__ == "__main__":
    raise SystemExit(main())
