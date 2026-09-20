import ast
import importlib
import inspect
import multiprocessing
import os
import pkgutil
import site
from pathlib import Path
from textwrap import dedent

BASE_DIR = "docs"


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
    print(f"processing {py_file}")
    try:
        src = Path(py_path).read_text(encoding="utf-8")
    except Exception:
        return None
    module_doc, functions, classes = extract_ast_docs(src)
    if not module_doc and (not functions) and (not classes):
        return None
    return (module_doc, functions, classes)


def extract_from_importable(name: str):
    print(f"processing {name}")
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


def process_file_task(data) -> None:
    py_file, root = data
    result = extract_from_file(py_file)
    if not result:
        return
    module_doc, functions, classes = result
    rel = os.path.relpath(py_file, root)
    module_name = rel.replace(os.sep, ".").replace(".py", "")
    folder, out_path = file_to_md_paths(py_file, root)
    md = format_markdown(module_name, module_doc, functions, classes)
    save_markdown(folder, out_path, md)


def main() -> None:
    Path(BASE_DIR).mkdir(exist_ok=True, parents=True)
    importable = [m.name for m in pkgutil.iter_modules()]
    roots = [*site.getsitepackages(), site.getusersitepackages()]
    py_files = []
    for r in roots:
        if not Path(r).is_dir():
            continue
        py_files.extend(((str(path), str(path.parent)) for path in Path(r).rglob("*.py")))
    with multiprocessing.Pool(8) as pool:
        pool.map(process_importable_task, importable)
        pool.map(process_file_task, py_files)


if __name__ == "__main__":
    main()
