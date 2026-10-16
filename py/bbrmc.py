import sys
from pathlib import Path

import tree_sitter_python as tsp
from tree_sitter import Language, Parser, Query

PY_LANGUAGE = Language(tsp.language())
parser = Parser(PY_LANGUAGE)
QUERY = "\n(class_definition\n    body: (block . (expression_statement (string) @docstring)))\n(function_definition\n    body: (block . (expression_statement (string) @docstring)))\n(module . (expression_statement (string) @docstring))\n"
'\n        source_code = path.read_text(encoding="utf-8")\n        tree = parser.parse(bytes(source_code, "utf8"))\n        root_node = tree.root_node\n        query = Query(PY_LANGUAGE, QUERY)\n        captures = query.captures(tree.root_node)\n        edits = []\n        for node, name in captures:\n            body_node = None\n            if node.parent and node.parent.type == "block":\n                body_node = node.parent\n            elif node.parent and node.parent.parent and node.parent.parent.type == "block":\n                body_node = node.parent.parent\n            if body_node and len(body_node.children) == 1:\n                edits.append((node.start_byte, node.end_byte, "pass"))\n            else:\n                edits.append((node.start_byte, node.end_byte, ""))\n        new_code = source_code\n        if edits:\n            for start, end, replacement in sorted(edits, key=lambda x: x[0], reverse=True):\n                new_code = new_code[:start] + replacement + new_code[end:]\n'


def process_file(path: Path) -> None:
    source_code = path.read_text(encoding="utf-8")
    tree = parser.parse(bytes(source_code, "utf8"))
    query = Query(PY_LANGUAGE, QUERY)
    captures = query.captures(tree.root_node)
    edits = []
    for node, name in captures:
        parent = node.parent.parent
        if len(parent.children) == 1:
            edits.append((node.start_byte, node.end_byte, "pass"))
        else:
            edits.append((node.start_byte, node.end_byte, ""))
    new_code = source_code
    for start, end, replacement in sorted(edits, key=lambda x: x[0], reverse=True):
        new_code = new_code[:start] + replacement + new_code[end:]
    path.write_text(new_code, encoding="utf-8")
    print(f"Processed: {path.name}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        process_file(Path(sys.argv[1]))
