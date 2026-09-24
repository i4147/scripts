import ast
import argparse
import zipfile
import shutil
import tempfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from typing import List


class CommentAndDocstringStripper(ast.NodeTransformer):
    def __init__(self, is_module=True):
        self.is_module = is_module
        self.docstring_removed = False

    def visit_FunctionDef(self, node):
        self.remove_docstring(node)
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.remove_docstring(node)
        return self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.remove_docstring(node)
        return self.generic_visit(node)

    def remove_docstring(self, node):

        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, (ast.Str, ast.Constant)):
            val = node.body[0].value
            if isinstance(val, ast.Str) or (isinstance(val, ast.Constant) and isinstance(val.value, str)):
                node.body.pop(0)


def process_content(content: bytes) -> bytes:
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        return content

    lines = decoded.splitlines(keepends=True)
    if not lines:
        return content

    header_lines = []
    start_idx = 0
    for i, line in enumerate(lines):
        if line.startswith(("#!", "# type:", "# fmt:")):
            header_lines.append(line)
            start_idx = i + 1
        else:
            break

    body_lines = lines[start_idx:]
    if not body_lines:
        return content

    try:
        tree = ast.parse("".join(body_lines))
    except SyntaxError:
        return content

    transformer = CommentAndDocstringStripper()
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)

    new_body = ast.unparse(tree)

    final_code = "".join(header_lines) + new_body

    if final_code.encode("utf-8") == content:
        return content

    return final_code.encode("utf-8")


def process_single_file(file_path: Path, base_dir: Path) -> str:
    try:
        original_content = file_path.read_bytes()
        new_content = process_content(original_content)

        if original_content != new_content:
            file_path.write_bytes(new_content)
            return str(file_path.relative_to(base_dir))
    except Exception as e:
        return f"Error processing {file_path}: {e}"
    return ""


def process_wheel(wheel_path: Path, base_dir: Path) -> List[str]:
    changed_files = []
    temp_dir = Path(tempfile.mkdtemp())
    try:
        with zipfile.ZipFile(wheel_path, "r") as zin:
            zin.extractall(temp_dir)

        internal_changes = []
        with ProcessPoolExecutor() as executor:
            files_to_process = []
            for p in temp_dir.rglob("*"):
                if p.suffix == ".py" or (p.is_file() and not p.suffix):
                    files_to_process.append(p)

            for f in files_to_process:
                res = process_single_file(f, temp_dir)
                if res:
                    internal_changes.append(f"{wheel_path.name} -> {res}")

        if internal_changes:
            with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for f in temp_dir.rglob("*"):
                    if f.is_file():
                        zout.write(f, f.relative_to(temp_dir))
            changed_files.extend(internal_changes)

    finally:
        shutil.rmtree(temp_dir)
    return changed_files


def main():
    parser = argparse.ArgumentParser(description="Strip docstrings and comments from Python files.")
    parser.add_argument("inputs", nargs="*", help="Files or directories to process")
    args = parser.parse_args()

    targets = args.inputs if args.inputs else ["."]

    work_items = []

    base_path = Path(targets[0]).resolve()

    for target in targets:
        p = Path(target).resolve()
        if p.is_dir():
            for file in p.rglob("*"):
                if file.is_file():
                    if file.suffix == ".py" or (not file.suffix and not file.name.startswith(".")):
                        work_items.append((file, "file"))
                    elif file.suffix == ".whl":
                        work_items.append((file, "wheel"))
        elif p.is_file():
            if p.suffix == ".py" or (not p.suffix and not p.name.startswith(".")):
                work_items.append((p, "file"))
            elif p.suffix == ".whl":
                work_items.append((p, "wheel"))

    print(f"Found {len(work_items)} items to inspect...")

    with ProcessPoolExecutor() as executor:
        files = [item[0] for item in work_items if item[1] == "file"]
        wheels = [item[0] for item in work_items if item[1] == "wheel"]

        file_results = executor.map(process_single_file, files, [base_path] * len(files))

        for rel_path in file_results:
            if rel_path:
                print(rel_path)

        for whl in wheels:
            whl_changes = process_wheel(whl, base_path)
            for change in whl_changes:
                print(change)


if __name__ == "__main__":
    main()
