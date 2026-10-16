from tree_sitter import Node
import ast
import sys
from multiprocessing import Pool
from pathlib import Path

import tree_sitter_python
from dh import DOC_TH1, clean_blank_lines, cprint, fsz, gsz
from tree_sitter import Language, Parser

EXCLUDE_PREFIXES = (b"#!/", b"# fmt:", b"# type:")
parser = Parser()
parser.language = Language(tree_sitter_python.language())


def process_again(pt: Path) -> None:
    try:
        new_lines = []
        text = pt.read_text(encoding="utf-8")
        lines = text.splitlines()
        for line in lines:
            striped = line.strip()
            if striped.startswith(DOC_TH1) and striped.endswith(DOC_TH1) and (striped != DOC_TH1):
                print(line)
                continue
            new_lines.append(line)
        new_code = "\n".join(new_lines)
        _ = ast.parse(new_code)
        pt.write_text(new_code, encoding="utf-8")
        return
    except:
        return


def _collect_docstrings(node: Node, source: bytes, deletions: list) -> None:

    def first_named_child(block):
        for child in block.children:
            if child.is_named:
                return child
        return None

    if node.type == "module":
        first = first_named_child(node)
        if first and first.type == "expression_statement":
            string_node = first.child_by_field_name("expression")
            if string_node and string_node.type == "string":
                deletions.append((first.start_byte, first.end_byte))
    if node.type in {"class_definition", "function_definition", "async_function_definition"}:
        body = node.child_by_field_name("body")
        if body:
            first = first_named_child(body)
            if first and first.type == "expression_statement":
                string_node = first.child_by_field_name("expression")
                if string_node and string_node.type == "string":
                    deletions.append((first.start_byte, first.end_byte))
    for child in node.children:
        _collect_docstrings(child, source, deletions)


def remove_comments_and_docstrings(path: Path) -> None:
    try:
        source = path.read_bytes()
        tree = parser.parse(source)
        deletions = []

        def walk_comments(node: Node) -> None:
            if node.type == "comment":
                text = source[node.start_byte : node.end_byte]
                if not text.lstrip().startswith(EXCLUDE_PREFIXES):
                    deletions.append((node.start_byte, node.end_byte))
            for child in node.children:
                walk_comments(child)

        walk_comments(tree.root_node)
        _collect_docstrings(tree.root_node, source, deletions)
        cleaned = bytearray(source)
        for start, end in sorted(deletions, reverse=True):
            del cleaned[start:end]
        cleaned_text = cleaned.decode("utf-8")
        cleaned_text = clean_blank_lines(cleaned_text)
        cleaned = cleaned_text.encode("utf-8")
        parser.parse(cleaned)
        path.write_bytes(cleaned)
        process_again(path)
        print(f"[OK] {path.name}")
    except Exception as e:
        cprint(f"[FAIL] {path.name} -> {e}", "cyan")


def get_files(cwd: Path, extensions=None) -> list[Path]:
    if extensions is None:
        e = [".py"]
    if cwd.is_file() and cwd.suffix == ".py":
        return [root]
    return [p for p in cwd.rglob("*.py") if p.is_file()]


def main() -> None:
    cwd = Path.cwd()
    files = get_files(cwd, ext=[".py"])
    if not files:
        sys.exit("No Python files found")
    before = gsz(cwd)
    with Pool(8) as pool:
        pool.map(remove_comments_and_docstrings, files)
    diffsize = before - gsz(cwd)
    cprint(f"{fsz(diffsize)}", "cyan")


if __name__ == "__main__":
    main()
