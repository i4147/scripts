from ast import AST
import ast
import multiprocessing as mp
import os
import pathlib

OUTPUT_DIR = "output"
EXCLUDE_DIRS = {"test", "tests", "examples", "output"}


def is_python_script(path: str) -> bool:
    if path.endswith(".py"):
        return True
    try:
        with pathlib.Path(path).open(encoding="utf-8", errors="ignore") as f:
            line = f.readline()
        return line.startswith("#!") and "python" in line.lower()
    except Exception:
        return False


def discover_python_files() -> list[str]:
    files = []
    for root, dirs, fnames in os.walk("."):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in fnames:
            path = os.path.join(root, fname)
            if is_python_script(path):
                files.append(path)
    return files


def mark_parents(node: ast.AST, parent: AST | None = None) -> None:
    for child in ast.iter_child_nodes(node):
        child._parent = node
        mark_parents(child, node)


def extract_from_file(path: str) -> tuple[str, dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    try:
        source = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except Exception:
        return (path, {}, {}, {}, {})
    mark_parents(tree)
    tl_classes, tl_funcs = ({}, {})
    nested_classes, nested_funcs = ({}, {})
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            src = ast.get_source_segment(source, node)
            if not src:
                continue
            parent = getattr(node, "_parent", None)
            is_toplevel = isinstance(parent, ast.Module)
            if isinstance(node, ast.ClassDef):
                if is_toplevel:
                    tl_classes[node.name] = src
                else:
                    nested_classes[node.name] = src
            elif isinstance(node, ast.FunctionDef):
                if is_toplevel:
                    tl_funcs[node.name] = src
                else:
                    nested_funcs[node.name] = src
    return (path, tl_classes, tl_funcs, nested_classes, nested_funcs)


def write_output(path: str, data: dict[str, str]) -> None:
    with pathlib.Path(path).open("w", encoding="utf-8") as f:
        f.writelines((src.rstrip() + "\n\n" for _name, src in sorted(data.items())))


def main() -> None:
    pathlib.Path(OUTPUT_DIR).mkdir(exist_ok=True, parents=True)
    files = discover_python_files()
    if not files:
        print("No Python files found.")
        return
    with mp.Pool(mp.cpu_count()) as pool:
        results = pool.map(extract_from_file, files)
    tl_classes, tl_funcs = ({}, {})
    nested_classes, nested_funcs = ({}, {})
    for _, c, f, nc, nf in results:
        tl_classes.update(c)
        tl_funcs.update(f)
        nested_classes.update(nc)
        nested_funcs.update(nf)
    write_output(os.path.join(OUTPUT_DIR, "classes.py"), tl_classes)
    write_output(os.path.join(OUTPUT_DIR, "functions.py"), tl_funcs)
    write_output(os.path.join(OUTPUT_DIR, "nested_classes.py"), nested_classes)
    write_output(os.path.join(OUTPUT_DIR, "nested_functions.py"), nested_funcs)
    print("=== Top-Level Classes ===")
    for n in sorted(tl_classes):
        print(" -", n)
    print("\n=== Top-Level Functions ===")
    for n in sorted(tl_funcs):
        print(" -", n)
    print("\n=== Nested Classes ===")
    for n in sorted(nested_classes):
        print(" -", n)
    print("\n=== Nested Functions ===")
    for n in sorted(nested_funcs):
        print(" -", n)
    print("\nOutputs saved to:", OUTPUT_DIR)


if __name__ == "__main__":
    main()
