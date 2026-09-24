import argparse
import zipfile
import tempfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from tree_sitter import Language, Parser
import tree_sitter_python


PY_LANGUAGE = Language(tree_sitter_python.language())
parser = Parser(PY_LANGUAGE)


def strip_docstrings(source_bytes: bytes) -> bytes:
    tree = parser.parse(source_bytes)

    query = PY_LANGUAGE.query("""
        (function_definition body: (block (expression_statement (string)) @docstring))
        (class_definition body: (block (expression_statement (string)) @docstring))
    """)

    captures = query.captures(tree.root_node)
    if not captures:
        return source_bytes

    edits = []
    for node, _ in reversed(captures):
        if node.type == "string":
            edits.append((node.start_byte, node.end_byte))

    source = source_bytes.decode("utf-8")

    new_source = source
    for start, end in edits:
        new_source = new_source[:start] + new_source[end:]

    return new_source.encode("utf-8")


def process_file(file_path: Path):
    try:
        content = file_path.read_bytes()

        stripped = strip_docstrings(content)

        if stripped != content:
            file_path.write_bytes(stripped)
            return str(file_path)
    except Exception:
        pass
    return None


def process_wheel(whl_path: Path):
    changed_files = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        with zipfile.ZipFile(whl_path, "r") as z:
            z.extractall(tmp_path)

        for p in tmp_path.rglob("*"):
            if p.is_file() and (p.suffix == ".py" or not p.suffix):
                if process_file(p):
                    changed_files.append(f"{whl_path.name} -> {p.relative_to(tmp_path)}")

        if changed_files:
            with zipfile.ZipFile(whl_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for f in tmp_path.rglob("*"):
                    z.write(f, f.relative_to(tmp_path))
    return changed_files


def main():
    parser_args = argparse.ArgumentParser()
    parser_args.add_argument("inputs", nargs="*", default=["."])
    args = parser_args.parse_args()

    targets = [Path(i) for i in args.inputs]
    all_files = []
    all_wheels = []

    for t in targets:
        items = [t] if t.is_file() else t.rglob("*")
        for item in items:
            if item.is_file():
                if item.suffix == ".py" or (not item.suffix and not item.name.startswith(".")):
                    all_files.append(item)
                elif item.suffix == ".whl":
                    all_wheels.append(item)

    with ProcessPoolExecutor() as exe:
        for res in exe.map(process_file, all_files):
            if res:
                print(res)

        for whl in all_wheels:
            for change in process_wheel(whl):
                print(change)


if __name__ == "__main__":
    main()
