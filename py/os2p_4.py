from ast import Attribute
from ast import AST
import ast
import sys
from pathlib import Path

from dh import fsz, get_files, gsz, mpf
from termcolor import cprint


def process_file(path):
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)

        class OsPathTransformer(ast.NodeTransformer):
            def visit_Call(self, node):
                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and (node.func.value.id == "os")
                    and (node.func.attr == "path")
                ):
                    if isinstance(node.func.value, ast.Attribute) and node.func.attr == "join":
                        print(
                            f"Warning: os.path.join found in {path}. Requires manual review for Path division operator. Node: {ast.dump(node)}"
                        )
                        return node
                    if node.func.attr == "listdir":
                        print(
                            f"Info: os.listdir found in {path}. Consider using Path(path).iterdir(). Node: {ast.dump(node)}"
                        )
                        return node
                    if node.func.attr == "remove":
                        print(f"Info: os.remove found in {path}. Replacing with Path.unlink(). Node: {ast.dump(node)}")
                        new_node = ast.Call(
                            func=ast.Attribute(value=ast.Name(id="Path"), attr="unlink", ctx=ast.Load()),
                            args=node.args,
                            keywords=node.keywords,
                        )
                        return ast.copy_location(new_node, node)
                    if node.func.attr == "splitext":
                        print(
                            f"Info: os.path.splitext found in {path}. Replacing with Path.stem/suffix. Node: {ast.dump(node)}"
                        )
                        return node
                elif (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "os"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and ("remove" in node.args[0].value)
                ):
                    print(
                        f"Warning: Direct os.remove(string) call found in {path}. Consider using Path.unlink(). Node: {ast.dump(node)}"
                    )
                    return node
                return self.generic_visit(node)

            def visit_Attribute(self, node) -> AST | Attribute:
                if isinstance(node.value, ast.Name) and node.value.id == "os" and (node.attr == "remove"):
                    print(
                        f"Info: os.remove attribute found in {path}. Replacing with Path.unlink(). Node: {ast.dump(node)}"
                    )
                    new_node = ast.Attribute(value=ast.Name(id="Path"), attr="unlink", ctx=ast.Load())
                    return ast.copy_location(new_node, node)
                return self.generic_visit(node)

        transformer = OsPathTransformer()
        new_tree = transformer.visit(tree)
        has_pathlib_import = any(
            (
                isinstance(node, ast.Import)
                and any((alias.name == "pathlib" for alias in node.names))
                or (isinstance(node, ast.ImportFrom) and node.module == "pathlib")
                for node in ast.walk(new_tree)
            )
        )
        if not has_pathlib_import:
            import_pathlib = ast.Import(names=[ast.alias(name="Path")])
            ast.fix_missing_locations(import_pathlib)
            new_tree.body.insert(0, import_pathlib)
            print(f"Info: Added import Path from pathlib to {path}")
        ast.fix_missing_locations(new_tree)
        new_content = ast.unparse(new_tree)
        try:
            ast.parse(new_content)
            print(f"Successfully validated and refactored: {path}")
            return (new_content, True)
        except SyntaxError as e:
            print(f"Syntax error in refactored {path}: {e}")
            return (content, False)
    except Exception as e:
        print(f"Error processing {path}: {e}")
        return (None, False)


def main() -> None:
    root_dir = Path.cwd()
    before = gsz(root_dir)
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(root_dir)
    results = mpf(process_file, files)
    for result in results:
        if result:
            pass
    diffsize = before - gsz(root_dir)
    cprint(f"space change : {fsz(diffsize)}", "cyan")


if __name__ == "__main__":
    sys.exit(main())
