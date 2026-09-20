from tree_sitter import Parser
from tree_sitter import Node
import sys
from pathlib import Path

import tree_sitter_cpp
import tree_sitter_python
import tree_sitter_rust
from dh import clean_blank_lines, mpf
from tree_sitter import Language, Parser

LANGUAGES = {
    ".py": tree_sitter_python.language(),
    ".rs": tree_sitter_rust.language(),
    ".cpp": tree_sitter_cpp.language(),
    ".cc": tree_sitter_cpp.language(),
    ".cxx": tree_sitter_cpp.language(),
    ".hpp": tree_sitter_cpp.language(),
    ".h": tree_sitter_cpp.language(),
    ".hh": tree_sitter_cpp.language(),
    ".hxx": tree_sitter_cpp.language(),
}
EXCLUDE_PREFIXES = (b"#!/", b"# fmt:", b"# type:")


def get_parser(lang) -> Parser:
    parser = Parser()
    parser.language = Language(lang)
    return parser


def _collect_python_docstrings(node: Node, deletions) -> None:

    def first_named_child(block):
        for child in block.children:
            if child.is_named:
                return child
        return None

    if node.type == "module":
        first = first_named_child(node)
        if first and first.type == "expression_statement":
            expr = first.child_by_field_name("expression")
            if expr and expr.type == "string":
                deletions.append((first.start_byte, first.end_byte))
    if node.type in {"class_definition", "function_definition", "async_function_definition"}:
        body = node.child_by_field_name("body")
        if body:
            first = first_named_child(body)
            if first and first.type == "expression_statement":
                expr = first.child_by_field_name("expression")
                if expr and expr.type == "string":
                    deletions.append((first.start_byte, first.end_byte))
    for child in node.children:
        _collect_python_docstrings(child, deletions)


def process_file(path: Path) -> None:
    try:
        ext = path.suffix.lower()
        lang = LANGUAGES.get(ext)
        if not lang:
            return
        parser = get_parser(lang)
        source = path.read_bytes()
        tree = parser.parse(source)
        deletions = []

        def walk(node: Node) -> None:
            if node.type == "comment":
                text = source[node.start_byte : node.end_byte]
                if ext == ".py" and text.lstrip().startswith(EXCLUDE_PREFIXES):
                    return
                deletions.append((node.start_byte, node.end_byte))
            for child in node.children:
                walk(child)

        walk(tree.root_node)
        if ext == ".py":
            _collect_python_docstrings(tree.root_node, deletions)
        if not deletions:
            return
        cleaned = bytearray(source)
        for start, end in sorted(deletions, reverse=True):
            del cleaned[start:end]
        cleaned_text = cleaned.decode("utf-8")
        cleaned_text = clean_blank_lines(cleaned_text)
        cleaned = cleaned_text.encode("utf-8")
        parser.parse(cleaned)
        path.write_bytes(cleaned)
        print(f"[OK] {path}")
    except Exception as e:
        print(f"[FAIL] {path} -> {e}")


def collect_supported_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in LANGUAGES else []
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in LANGUAGES]


def main() -> None:
    root = Path.cwd()
    files = collect_supported_files(root)
    if not files:
        sys.exit("No supported files found")
    mpf(process_file, files)


if __name__ == "__main__":
    main()
