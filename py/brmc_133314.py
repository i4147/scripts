
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final
import astor
from dh import cprint, fsz, get_pyfiles, gsz, mpf3

SINGLE_QUOTE: Final[str] = "'"
DOUBLE_QUOTE: Final[str] = '"'
triplex2 = {'""""""', "''''''"}
DOCTH = '"""', "'''"
PRESERVE_BEFORE_CODE = "from ", "import ", "def ", "class "


@dataclass(slots=True)
class StrippingStats:
    lines_removed: int = 0
    was_modified: bool = False


class StringLiteralStripper:
    __slots__ = ()

    @staticmethod
    def _is_standalone_string(stripped: str) -> bool:
        if not stripped:
            return False
        if stripped.startswith(DOCTH) and stripped.endswith(DOCTH) and stripped not in triplex2:
            return True
        return False

    @classmethod
    def strip(cls, code: str) -> tuple[str, StrippingStats]:
        lines = code.splitlines()
        new_lines: list[str] = []
        stats = StrippingStats()
        code_started = False
        for line in lines:
            stripped = line.strip()
            if not code_started and not stripped.startswith(PRESERVE_BEFORE_CODE):
                new_lines.append(line)
                continue
            code_started = True
            if cls._is_standalone_string(stripped):
                stats.lines_removed += 1
                continue
            new_lines.append(line)
        if stats.lines_removed > 0:
            new_code = "\n".join(new_lines)
            try:
                ast.parse(new_code)
                stats.was_modified = True
                return new_code, stats
            except SyntaxError:
                return code, StrippingStats()
        return code, stats


class DocstringRemover(ast.NodeTransformer):
    __slots__ = ("preserve_module_docstring",)

    def __init__(self, preserve_module_docstring: bool = True) -> None:
        super().__init__()
        self.preserve_module_docstring = preserve_module_docstring

    @staticmethod
    def _is_docstring(node: ast.AST) -> bool:
        return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)

    def _remove_docstring(self, node: ast.AST) -> ast.AST:
        if not hasattr(node, "body") or not node.body:
            return node
        if self._is_docstring(node.body[0]):
            if len(node.body) == 1:
                node.body = [ast.Pass()]
            else:
                node.body = node.body[1:]
        return node

    def visit_Module(self, node: ast.Module) -> ast.Module:
        if self.preserve_module_docstring:
            self.generic_visit(node)
            return node
        return self._remove_docstring(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        self.generic_visit(node)
        return self._remove_docstring(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self.generic_visit(node)
        return self._remove_docstring(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AsyncFunctionDef:
        self.generic_visit(node)
        return self._remove_docstring(node)


def process_file(path: (str | Path)) -> bool:
    path = Path(path)
    before_size = gsz(path)
    try:
        code = path.read_text(encoding="utf-8")
        first_line = ""
        if code.startswith("#!"):
            lines = code.splitlines(keepends=True)
            first_line = lines[0]
            code = "".join(lines[1:])
        preprocessed_code, strip_stats = StringLiteralStripper.strip(code)
        try:
            tree = ast.parse(preprocessed_code)
        except SyntaxError as e:
            cprint(f"❌ {path.name}: Syntax error - {e}", "yellow")
            return False
        transformer = DocstringRemover(preserve_module_docstring=True)
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        new_code = astor.to_source(new_tree)
        if first_line:
            new_code = first_line + new_code
        try:
            ast.parse(new_code)
        except SyntaxError:
            cprint(f"❌ {path.name}: Invalid code after transformation", "yellow")
            return False
        if len(new_code.strip()) == len(code.strip()):
            print(f"{path.name} (no change)")
            return False
        path.write_text(new_code, encoding="utf-8")
        after_size = gsz(path)
        size_diff = before_size - after_size
        if size_diff > 0:
            ratio = size_diff / before_size * 100
            print(f"✅ {path.name}", end=" | ")
            cprint(f"-{fsz(size_diff)} | {ratio:.1f}%", "cyan")
            return True
        else:
            cprint(f"{path.name} (no size change)", (147, 147, 147))
            return False
    except Exception as e:
        cprint(f"❌ {path.name}: {type(e).__name__}: {e}", "yellow")
        return False


def main() -> None:
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_pyfiles(Path.cwd())
    if not files:
        print("No Python files found.")
        return
    print(f"Processing {len(files)} file(s)...\n")
    if len(files) == 1:
        process_file(files[0])
    else:
        results = mpf3(process_file, files)
        successful = sum(1 for r in results if r)
        print(f"\nModified {successful}/{len(files)} file(s)")


if __name__ == "__main__":
    main()
