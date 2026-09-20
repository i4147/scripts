import ast
import importlib
import inspect
import os
import sys
import zipfile
from multiprocessing import Pool
from pathlib import Path
from textwrap import dedent
from dh import get_files

BASE_DIR = Path("docs")


def format_markdown(module_name: str, module_doc: str, functions, classes) -> str:
    parts = [f"# Module `{module_name}`\n"]
    if module_doc:
        parts.extend(("## Module Doc\n", module_doc + "\n"))
    if functions:
        parts.append("## Functions\n")
        for name, doc in functions:
            parts.extend((f"### `{name}()`\n", doc + "\n"))
    if classes:
        parts.append("## Classes\n")
        for name, doc in classes:
            parts.extend((f"### `{name}`\n", doc + "\n"))
    return "\n".join(parts).strip() + "\n"


def extract_ast_docs(src: str) -> tuple[str, list, list]:
    try:
        tree = ast.parse(src)
    except Exception:
        return ("", [], [])
    module_doc = dedent(ast.get_docstring(tree) or "").strip()
    functions = []
    classes = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node) or ""
            doc = dedent(doc).strip()
            if doc:
                functions.append((node.name, doc))
        elif isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or ""
            doc = dedent(doc).strip()
            if doc:
                classes.append((node.name, doc))
    return (module_doc, functions, classes)


def extract_from_file(py_path: str) -> tuple[str, str, str, list, list]:
    try:
        src = Path(py_path).read_text(encoding="utf-8")
    except Exception:
        return None
    module_doc, functions, classes = extract_ast_docs(src)
    if not module_doc and (not functions) and (not classes):
        return None
    return (module_doc, functions, classes)


def extract_from_importable(name: str):
    try:
        module = importlib.import_module(name)
    except Exception:
        return None
    try:
        src = inspect.getsource(module)
        return extract_ast_docs(src)
    except Exception:
        doc = dedent(inspect.getdoc(module) or "").strip()
        if not doc:
            return None
        return (doc, [], [])


def module_to_md_paths(name: str) -> tuple[str, str]:
    parts = name.split(".")
    folder = os.path.join(BASE_DIR, *parts[:-1])
    filename = f"{parts[-1]}.md"
    return (folder, os.path.join(folder, filename))


def file_to_md_paths(py_file: str, root: str) -> tuple[str, str]:
    rel = os.path.relpath(py_file, root)
    parts = rel.split(os.sep)
    parts[-1] = parts[-1].replace(".py", ".md")
    folder = os.path.join(BASE_DIR, *parts[:-1])
    outfile = os.path.join(BASE_DIR, *parts)
    return (folder, outfile)


def save_markdown(folder: str, path: str, content: str) -> None:
    Path(folder).mkdir(exist_ok=True, parents=True)
    Path(path).write_text(content, encoding="utf-8")


def process_importable_task(name: str) -> None:
    result = extract_from_importable(name)
    if not result:
        return
    module_doc, functions, classes = result
    folder, out_path = module_to_md_paths(name)
    md = format_markdown(name, module_doc, functions, classes)
    save_markdown(folder, out_path, md)


def process_file_task(py_file) -> None:
    result = extract_from_file(str(py_file))
    root = str(py_file.parent)
    if not result:
        return
    module_doc, functions, classes = result
    rel = os.path.relpath(py_file)
    module_name = rel.replace(os.sep, ".").replace(".py", "")
    folder, out_path = file_to_md_paths(py_file, root)
    md = format_markdown(module_name, module_doc, functions, classes)
    save_markdown(folder, out_path, md)


def create_zip(diretory) -> None:
    with zipfile.ZipFile("docs.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(directory):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, directory)
                z.write(full, arc)


def main() -> None:
    if not BASE_DIR.exists():
        BASE_DIR.mkdir(exist_ok=True)
    root_dir = Path.cwd()
    args = sys.argv[1:]
    files = [Path(arg) for arg in args] if args else get_files(root_dir, extensions=[".py"])
    with Pool(8) as pool:
        pool.map(process_file_task, files)


if __name__ == "__main__":
    main()
