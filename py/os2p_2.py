import ast
import sys
from pathlib import Path
from typing import List, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import traceback

from dh import fsz, get_files, gsz
from termcolor import cprint


class PathlibTransformer(ast.NodeTransformer):
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.needs_path_import = False
        self.warnings: List[str] = []
        self.infos: List[str] = []

    def visit_Import(self, node: ast.Import) -> ast.Import:
        for alias in node.names:
            if alias.name == "pathlib" or alias.name == "Path":
                self.needs_path_import = False
        return self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom:
        if node.module == "pathlib":
            for alias in node.names:
                if alias.name == "Path":
                    self.needs_path_import = False
        return self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> ast.AST:

        if self._is_os_path_attr(node, "join"):
            self.infos.append(f"os.path.join -> Path / operator")
            new_node = self._transform_join(node)
            return new_node if new_node else self.generic_visit(node)

        if self._is_os_path_attr(node, "dirname"):
            self.infos.append(f"os.path.dirname -> Path.parent")
            new_node = ast.Call(
                func=ast.Attribute(value=self._ensure_path(node.args[0]), attr="parent", ctx=ast.Load()),
                args=[],
                keywords=[],
            )
            return ast.copy_location(new_node, node)

        if self._is_os_path_attr(node, "basename"):
            self.infos.append(f"os.path.basename -> Path.name")
            new_node = ast.Call(
                func=ast.Attribute(value=self._ensure_path(node.args[0]), attr="name", ctx=ast.Load()),
                args=[],
                keywords=[],
            )
            return ast.copy_location(new_node, node)

        if self._is_os_path_attr(node, "splitext"):
            self.infos.append(f"os.path.splitext -> Path.stem/.suffix")

            path_var = self._ensure_path(node.args[0])
            new_node = ast.Tuple(
                elts=[
                    ast.Attribute(value=path_var, attr="stem", ctx=ast.Load()),
                    ast.Attribute(value=path_var, attr="suffix", ctx=ast.Load()),
                ],
                ctx=ast.Load(),
            )
            return ast.copy_location(new_node, node)

        if self._is_os_path_attr(node, "exists"):
            self.infos.append(f"os.path.exists -> Path.exists()")
            new_node = ast.Call(
                func=ast.Attribute(value=self._ensure_path(node.args[0]), attr="exists", ctx=ast.Load()),
                args=[],
                keywords=[],
            )
            return ast.copy_location(new_node, node)

        if self._is_os_path_attr(node, "isfile"):
            self.infos.append(f"os.path.isfile -> Path.is_file()")
            new_node = ast.Call(
                func=ast.Attribute(value=self._ensure_path(node.args[0]), attr="is_file", ctx=ast.Load()),
                args=[],
                keywords=[],
            )
            return ast.copy_location(new_node, node)

        if self._is_os_path_attr(node, "isdir"):
            self.infos.append(f"os.path.isdir -> Path.is_dir()")
            new_node = ast.Call(
                func=ast.Attribute(value=self._ensure_path(node.args[0]), attr="is_dir", ctx=ast.Load()),
                args=[],
                keywords=[],
            )
            return ast.copy_location(new_node, node)

        if self._is_os_path_attr(node, "abspath"):
            self.infos.append(f"os.path.abspath -> Path.resolve()")
            new_node = ast.Call(
                func=ast.Attribute(
                    value=self._ensure_path(node.args[0] if node.args else ast.Constant(value=".")),
                    attr="resolve",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )
            return ast.copy_location(new_node, node)

        if self._is_os_func(node, "remove"):
            self.infos.append(f"os.remove -> Path.unlink()")
            new_node = ast.Call(
                func=ast.Attribute(value=self._ensure_path(node.args[0]), attr="unlink", ctx=ast.Load()),
                args=[],
                keywords=[],
            )
            return ast.copy_location(new_node, node)

        if self._is_os_func(node, "listdir"):
            self.warnings.append(f"os.listdir requires manual review - consider Path.iterdir() or Path.glob('*')")
            return self.generic_visit(node)

        if self._is_os_func(node, "makedirs"):
            self.infos.append(f"os.makedirs -> Path.mkdir(parents=True)")
            new_node = ast.Call(
                func=ast.Attribute(value=self._ensure_path(node.args[0]), attr="mkdir", ctx=ast.Load()),
                args=[],
                keywords=[
                    ast.keyword(arg="parents", value=ast.Constant(value=True)),
                    ast.keyword(arg="exist_ok", value=ast.Constant(value=True)),
                ],
            )
            return ast.copy_location(new_node, node)

        if self._is_os_func(node, "mkdir"):
            self.infos.append(f"os.mkdir -> Path.mkdir()")
            new_node = ast.Call(
                func=ast.Attribute(value=self._ensure_path(node.args[0]), attr="mkdir", ctx=ast.Load()),
                args=[],
                keywords=[ast.keyword(arg="exist_ok", value=ast.Constant(value=False))],
            )
            return ast.copy_location(new_node, node)

        if self._is_os_func(node, "rename"):
            self.infos.append(f"os.rename -> Path.rename()")
            new_node = ast.Call(
                func=ast.Attribute(value=self._ensure_path(node.args[0]), attr="rename", ctx=ast.Load()),
                args=[self._ensure_path(node.args[1])],
                keywords=[],
            )
            return ast.copy_location(new_node, node)

        if self._is_os_func(node, "getcwd"):
            self.infos.append(f"os.getcwd -> Path.cwd()")
            new_node = ast.Call(
                func=ast.Attribute(value=ast.Name(id="Path", ctx=ast.Load()), attr="cwd", ctx=ast.Load()),
                args=[],
                keywords=[],
            )
            return ast.copy_location(new_node, node)

        return self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        if isinstance(node.value, ast.Name) and node.value.id == "os":
            if node.attr == "path":
                return node
            elif node.attr in ["remove", "rename", "mkdir", "listdir"]:
                self.warnings.append(f"Direct os.{node.attr} reference found - may need manual refactoring")

        return self.generic_visit(node)

    def _is_os_path_attr(self, node: ast.Call, attr: str) -> bool:
        return (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "os"
            and node.func.value.attr == "path"
            and node.func.attr == attr
        )

    def _is_os_func(self, node: ast.Call, func_name: str) -> bool:
        return (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
            and node.func.attr == func_name
        )

    def _ensure_path(self, node: ast.AST) -> ast.AST:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "Path":
                return node

        return ast.Call(func=ast.Name(id="Path", ctx=ast.Load()), args=[node], keywords=[])

    def _transform_join(self, node: ast.Call) -> Optional[ast.AST]:
        if not node.args:
            return None

        result = self._ensure_path(node.args[0])
        for arg in node.args[1:]:
            result = ast.BinOp(left=result, op=ast.Div(), right=arg)
            ast.copy_location(result, node)

        return result


def process_file(file_path: Path) -> Tuple[Optional[str], bool, List[str], List[str]]:
    try:
        original_content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(original_content)

        transformer = PathlibTransformer(file_path)
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)

        if transformer.needs_path_import:
            path_import = ast.ImportFrom(module="pathlib", names=[ast.alias(name="Path")], level=0)
            new_tree.body.insert(0, path_import)
            transformer.infos.append("Added 'from pathlib import Path'")

        new_content = ast.unparse(new_tree)
        ast.parse(new_content)

        for info in transformer.infos:
            cprint(f"  ℹ️ {info}", "cyan", attrs=["dark"])
        for warning in transformer.warnings:
            cprint(f"  ⚠️ {warning}", "yellow")

        if transformer.infos or transformer.warnings:
            cprint(f"✓ Refactored: {file_path}", "green")

        return (new_content, True, transformer.warnings, transformer.infos)

    except SyntaxError as e:
        cprint(f"✗ Syntax error in {file_path}: {e}", "red")
        return (None, False, [], [])
    except Exception as e:
        cprint(f"✗ Error processing {file_path}: {e}", "red")
        if "--verbose" in sys.argv:
            traceback.print_exc()
        return (None, False, [], [])


def write_backup(file_path: Path) -> Path:
    backup_path = file_path.with_suffix(file_path.suffix + ".bak")
    backup_path.write_text(file_path.read_text(encoding="utf-8"))
    return backup_path


def main() -> int:
    root_dir = Path.cwd()
    before_size = gsz(root_dir)

    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    verbose = "--verbose" in args
    no_backup = "--no-backup" in args

    paths = [arg for arg in args if not arg.startswith("--")]

    files: List[Path] = []
    if paths:
        for path_str in paths:
            p = Path(path_str)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(root_dir)

    python_files = [f for f in files if f.suffix == ".py"]

    if not python_files:
        cprint("No Python files found to process.", "yellow")
        return 0

    cprint(f"Found {len(python_files)} Python files to process", "cyan")
    if dry_run:
        cprint("DRY RUN - No files will be modified", "yellow")

    results = {}
    total_warnings = 0
    total_changes = 0

    with ProcessPoolExecutor() as executor:
        future_to_file = {executor.submit(process_file, f): f for f in python_files}

        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                new_content, success, warnings, infos = future.result()
                results[file_path] = (new_content, success, warnings, infos)
                total_warnings += len(warnings)
                total_changes += len(infos)
            except Exception as e:
                cprint(f"✗ Failed to process {file_path}: {e}", "red")
                results[file_path] = (None, False, [], [])

    modified_count = 0
    for file_path, (new_content, success, warnings, infos) in results.items():
        if success and new_content and (infos or warnings):
            if not dry_run:
                if not no_backup:
                    backup_path = write_backup(file_path)
                    cprint(f"  📦 Backup created: {backup_path}", "white", attrs=["dark"])
                file_path.write_text(new_content, encoding="utf-8")
                modified_count += 1
            else:
                cprint(f"  🔍 Would modify: {file_path}", "yellow")

    after_size = gsz(root_dir)
    size_diff = before_size - after_size

    cprint("\n" + "=" * 50, "cyan")
    cprint("REFACTORING SUMMARY", "cyan", attrs=["bold"])
    cprint(f"  Files processed: {len(python_files)}", "white")
    cprint(f"  Files modified: {modified_count}", "green" if modified_count > 0 else "white")
    cprint(f"  Total changes: {total_changes}", "green" if total_changes > 0 else "white")
    cprint(f"  Total warnings: {total_warnings}", "yellow" if total_warnings > 0 else "white")
    cprint(f"  Space change: {fsz(size_diff)}", "cyan")

    if dry_run:
        cprint("\n⚠️  This was a dry run. Run without --dry-run to apply changes.", "yellow")

    return 0


if __name__ == "__main__":
    sys.exit(main())
