import tree_sitter_python as tsp
from tree_sitter import Language, Parser, Query

PY_LANGUAGE = Language(tsp.language())
parser = Parser(PY_LANGUAGE)
QUERY = """
(class_definition
    body: (block . (expression_statement (string) @docstring)))
(function_definition
    body: (block . (expression_statement (string) @docstring)))
(module . (expression_statement (string) @docstring))
"""


def process_file(path: Path) -> None:
    try:
        source_code = path.read_text(encoding="utf-8")
        tree = parser.parse(bytes(source_code, "utf8"))
        root_node = tree.root_node
        query = Query(PY_LANGUAGE, QUERY)
        captures = query.captures(tree.root_node)
        edits = []
        for node, name in captures:
            body_node = None
            if node.parent and node.parent.type == "block":
                body_node = node.parent
            elif node.parent and node.parent.parent and node.parent.parent.type == "block":
                body_node = node.parent.parent
            if body_node and len(body_node.children) == 1:
                edits.append((node.start_byte, node.end_byte, "pass"))
            else:
                edits.append((node.start_byte, node.end_byte, ""))
        new_code = source_code
        if edits:
            for start, end, replacement in sorted(edits, key=lambda x: x[0], reverse=True):
                new_code = new_code[:start] + replacement + new_code[end:]
            path.write_text(new_code, encoding="utf-8")
            print(f"Processed: {path.name}")
        else:
            print(f"{path.name} (no docstrings found or removed)")
    except Exception as e:
        print(f"❌ {path.name}: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
        if file_path.is_file():
            process_file(file_path)
        else:
            print(f"Error: File not found at {sys.argv[1]}")
    else:
        print("Usage: python your_script_name.py <path_to_python_file>")
