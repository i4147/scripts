import ast
import difflib
import re
import sys
from pathlib import Path

from dh import cprint, get_pyfiles

REPLACEMENTS = {
    "os.path.join": (
        "pathlib",
        "Path",
        "lambda *args: Path(*args[:-1]).joinpath(args[-1]) if len(args) > 1 else Path(*args)",
    ),
    "path.exists": ("pathlib", "Path", "lambda p: Path(p).exists()"),
    "path.isdir": ("pathlib", "Path", "lambda p: Path(p).is_dir()"),
    "path.isfile": ("pathlib", "Path", "lambda p: Path(p).is_file()"),
    "path.abspath": ("pathlib", "Path", "lambda p: Path(p).resolve()"),
    "path.realpath": ("pathlib", "Path", "lambda p: Path(p).resolve()"),
    "path.basename": ("pathlib", "Path", "lambda p: Path(p).name"),
    "path.dirname": ("pathlib", "Path", "lambda p: Path(p).parent"),
    "path.split": ("pathlib", "Path", "lambda p: (str(Path(p).parent), Path(p).name)"),
    "path.getmtime": ("pathlib", "Path", "lambda p: Path(p).stat().st_mtime"),
    "path.getsize": ("pathlib", "Path", "lambda p: Path(p).stat().st_size"),
    "path.relpath": ("pathlib", "Path", "lambda p, start='.': Path(p).resolve().relative_to(Path(start).resolve())"),
    "path.commonpath": ("pathlib", "Path", "lambda paths: Path(os.path.commonpath(paths))"),
    "path.samefile": ("pathlib", "Path", "lambda p1, p2: Path(p1).samefile(Path(p2))"),
    "path.expanduser": ("pathlib", "Path", "lambda p: Path(p).expanduser()"),
    "path.expandvars": ("pathlib", "Path", "lambda p: Path(p).expandvars()"),
    "path.normcase": ("pathlib", "Path", "lambda p: Path(p).resolve().as_posix()"),
    "makedirs": ("shutil", "Path", "lambda p, *a, **k: Path(p).mkdir(*a, **k)"),
    "mkdir": ("pathlib", "Path", "lambda p: Path(p).mkdir(parents=False, exist_ok=False)"),
    "rmdir": ("pathlib", "Path", "lambda p: Path(p).rmdir()"),
    "remove": ("pathlib", "Path", "lambda p: Path(p).unlink()"),
    "rename": ("pathlib", "Path", "lambda src, dst: Path(src).rename(dst)"),
    "replace": ("pathlib", "Path", "lambda src, dst: Path(src).replace(dst)"),
    "listdir": ("pathlib", "Path", "lambda p='.': list(Path(p).iterdir())"),
    "walk": (
        "pathlib",
        "Path",
        "lambda top: ((str(p), [d.name for d in p.iterdir() if d.is_dir()], [f.name for f in p.iterdir() if f.is_file()]) for p in Path(top).rglob('*') if p.is_dir())",
    ),
    "stat": ("pathlib", "Path", "lambda p: Path(p).stat()"),
    "chdir": ("pathlib", "Path", "lambda p: os.chdir(p)"),
    "getcwd": ("pathlib", None, "lambda: Path.cwd()"),
    "environ": ("os", None, "os.environ"),
    "chmod": ("pathlib", "Path", "lambda p, mode: Path(p).chmod(mode)"),
    "chown": ("pathlib", "Path", "lambda p, uid, gid: Path(p).chown(uid, gid)"),
    "symlink": ("pathlib", "Path", "lambda src, dst: Path(dst).symlink_to(src)"),
    "readlink": ("pathlib", "Path", "lambda p: str(Path(p).readlink())"),
    "unlink": ("pathlib", "Path", "lambda p: Path(p).unlink()"),
    "rename": ("pathlib", "Path", "lambda src, dst: Path(src).rename(dst)"),
    "scandir": ("pathlib", "Path", "lambda p='.': Path(p).iterdir()"),
}


class OsUsageFinder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.uses_os = False
        self.os_import_name: str | None = None
        self.os_path_import_name: str | None = None
        self.os_used_attrs: set[str] = set()
        self.os_path_used_attrs: set[str] = set()

    def visit_Import(self, node) -> None:
        for alias in node.names:
            if alias.name == "os":
                self.uses_os = True
                self.os_import_name = alias.asname or "os"
            elif alias.name == "os.path":
                self.uses_os = True
                self.os_path_import_name = alias.asname or "os.path"
        self.generic_visit(node)

    def visit_ImportFrom(self, node) -> None:
        if node.module == "os":
            self.uses_os = True
            for alias in node.names:
                self.os_used_attrs.add(alias.name)
        elif node.module == "os.path":
            self.uses_os = True
            for alias in node.names:
                self.os_path_used_attrs.add(alias.name)
        self.generic_visit(node)

    def visit_Attribute(self, node) -> None:
        if isinstance(node.value, ast.Name) and node.value.id == self.os_import_name:
            self.uses_os = True
            self.os_used_attrs.add(node.attr)
        if isinstance(node.value, ast.Attribute) and (
            isinstance(node.value.value, ast.Name)
            and node.value.value.id == self.os_import_name
            and (node.value.attr == "path")
        ):
            self.uses_os = True
            self.os_path_used_attrs.add(node.attr)
        self.generic_visit(node)


def rewrite_os_to_pathlib(source, tree) -> str:
    source = re.sub("\\bos\\.path\\.join\\s*\\(\\s*([^)]*)\\s*\\)", lambda m: _join_replacer(m.group(1)), source)
    source = re.sub("\\bos\\.getcwd\\s*\\(\\s*\\)", "Path.cwd()", source)
    source = re.sub("\\bos\\.listdir\\s*\\(\\s*\\)", "list(Path().iterdir())", source)
    source = re.sub('\\bos\\.listdir\\s*\\(\\s*"([^"]+)"\\s*\\)', 'list(Path("\x01").iterdir())', source)
    source = re.sub("\\bos\\.listdir\\s*\\(\\s*\\'([^\\']+)\\'\\s*\\)", 'list(Path("\x01").iterdir())', source)
    for attr in [
        "exists",
        "isdir",
        "isfile",
        "abspath",
        "realpath",
        "basename",
        "dirname",
        "split",
        "getmtime",
        "getsize",
        "relpath",
        "samefile",
        "expanduser",
        "expandvars",
        "normcase",
    ]:
        pattern = f"\\bos\\.path\\.{attr}\\s*\\(\\s*([^)]*)\\s*\\)"
        repl = _make_pathlib_call(attr)
        source = re.sub(pattern, repl, source)
    for os_attr, (mod, imp, repl) in REPLACEMENTS.items():
        if mod is None and imp == "Path" and ("lambda" in repl):
            continue
        if os_attr[0] == "os" and os_attr[1] != "path":
            pattern = f"\\bos\\.{os_attr[1]}\\s*\\(\\s*([^)]*)\\s*\\)"
            if os_attr[1] in {
                "makedirs",
                "mkdir",
                "rmdir",
                "remove",
                "rename",
                "replace",
                "stat",
                "chmod",
                "chown",
                "symlink",
                "readlink",
                "unlink",
                "scandir",
            }:
                if os_attr[1] == "makedirs":
                    source = re.sub(
                        "\\bos\\.makedirs\\s*\\(\\s*([^,]+)\\s*(?:,\\s*([^)]+))?\\s*\\)",
                        lambda m: (
                            f"Path({m.group(1)}).mkdir(parents=True, exist_ok=True)"
                            if m.group(2) is None
                            else f"Path({m.group(1)}).mkdir({m.group(2)})"
                        ),
                        source,
                    )
                elif os_attr[1] == "mkdir":
                    source = re.sub(
                        "\\bos\\.mkdir\\s*\\(\\s*([^)]+)\\s*\\)",
                        "Path(\\1).mkdir(parents=False, exist_ok=False)",
                        source,
                    )
                elif os_attr[1] == "rmdir":
                    source = re.sub("\\bos\\.rmdir\\s*\\(\\s*([^)]+)\\s*\\)", "Path(\x01).rmdir()", source)
                elif os_attr[1] == "remove":
                    source = re.sub("\\bos\\.remove\\s*\\(\\s*([^)]+)\\s*\\)", "Path(\x01).unlink()", source)
                elif os_attr[1] == "rename":
                    source = re.sub(
                        "\\bos\\.rename\\s*\\(\\s*([^,]+)\\s*,\\s*([^)]+)\\s*\\)", "Path(\x01).rename(\x02)", source
                    )
                elif os_attr[1] == "replace":
                    source = re.sub(
                        "\\bos\\.replace\\s*\\(\\s*([^,]+)\\s*,\\s*([^)]+)\\s*\\)", "Path(\x01).replace(\x02)", source
                    )
                elif os_attr[1] == "stat":
                    source = re.sub("\\bos\\.stat\\s*\\(\\s*([^)]+)\\s*\\)", "Path(\x01).stat()", source)
                elif os_attr[1] == "chmod":
                    source = re.sub(
                        "\\bos\\.chmod\\s*\\(\\s*([^,]+)\\s*,\\s*([^)]+)\\s*\\)", "Path(\x01).chmod(\x02)", source
                    )
                elif os_attr[1] == "chown":
                    source = re.sub(
                        "\\bos\\.chown\\s*\\(\\s*([^,]+)\\s*,\\s*([^,]+)\\s*,\\s*([^)]+)\\s*\\)",
                        "Path(\x01).chown(\x02, \x03)",
                        source,
                    )
                elif os_attr[1] == "symlink":
                    source = re.sub(
                        "\\bos\\.symlink\\s*\\(\\s*([^,]+)\\s*,\\s*([^)]+)\\s*\\)",
                        "Path(\x02).symlink_to(\x01)",
                        source,
                    )
                elif os_attr[1] == "readlink":
                    source = re.sub("\\bos\\.readlink\\s*\\(\\s*([^)]+)\\s*\\)", "str(Path(\x01).readlink())", source)
                elif os_attr[1] == "unlink":
                    source = re.sub("\\bos\\.unlink\\s*\\(\\s*([^)]+)\\s*\\)", "Path(\x01).unlink()", source)
                elif os_attr[1] == "scandir":
                    source = re.sub("\\bos\\.scandir\\s*\\(\\s*([^)]*)\\s*\\)", "Path(\x01).iterdir()", source)
    if "Path(" in source and "from pathlib import Path" not in source:
        lines = source.splitlines(keepends=True)
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("import ") or line.strip().startswith("from "):
                insert_idx = i + 1
            elif line.strip() and (not line.strip().startswith("#")):
                break
        if insert_idx == 0:
            insert_idx = 1
        lines.insert(insert_idx, "from pathlib import Path\n")
        source = "".join(lines)
    return source


def _join_replacer(args) -> str:
    parts = [p.strip() for p in args.split(",") if p.strip()]
    if not parts:
        return "Path()"
    if len(parts) == 1:
        return f"Path({parts[0]})"
    return " / ".join([f"Path({parts[0]})", *parts[1:]])


def _make_pathlib_call(attr: str):
    mapping = {
        "exists": lambda p: f"Path({p}).exists()",
        "isdir": lambda p: f"Path({p}).is_dir()",
        "isfile": lambda p: f"Path({p}).is_file()",
        "abspath": lambda p: f"Path({p}).resolve()",
        "realpath": lambda p: f"Path({p}).resolve()",
        "basename": lambda p: f"Path({p}).name",
        "dirname": lambda p: f"Path({p}).parent",
        "split": lambda p: f"(str(Path({p}).parent), Path({p}).name)",
        "getmtime": lambda p: f"Path({p}).stat().st_mtime",
        "getsize": lambda p: f"Path({p}).stat().st_size",
        "relpath": lambda p: f"Path({p}).resolve().relative_to(Path('.').resolve())",
        "samefile": lambda p: f"Path({p}).exists() and Path({p}).samefile(Path({p}))",
        "expanduser": lambda p: f"Path({p}).expanduser()",
        "expandvars": lambda p: f"Path({p}).expandvars()",
        "normcase": lambda p: f"Path({p}).as_posix().lower()",
    }
    return mapping.get(attr, lambda p: f"Path({p}).{attr}()")


def process_file(path: Path) -> None:
    code = path.read_text(encoding="utf8")
    bakpath = path.with_name(path.name + ".bak")
    bakpath.write_text(code, encoding="utf-8")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        print(f"⚠️  Skipping unparseable file: {path} ({e})")
        return
    finder = OsUsageFinder()
    finder.visit(tree)
    if not finder.uses_os:
        return
    new_code = rewrite_os_to_pathlib(code, tree)
    if new_code.strip() == code.strip():
        cprint(f"{path.name} (no change)")
        return
    diff = list(
        difflib.unified_diff(
            code.splitlines(keepends=True),
            new_code.splitlines(keepends=True),
            fromfile=f"{path.name} (code)",
            tofile=f"{path} (refactored)",
            lineterm="",
        )
    )
    cprint("".join(diff))
    if diff:
        path.write_text(new_code, encoding="utf-8")
    return


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]
    in_place = "--in-place" in args
    files = [Path(p) for p in args] if args else get_pyfiles(cwd)
    if not files:
        print("No Python files found to process.")
        sys.exit(0)
    changed_count = 0
    for f in files:
        process_file(f)


if __name__ == "__main__":
    main()
