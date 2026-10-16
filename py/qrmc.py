import ast
import multiprocessing
import operator
import os
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor

PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)
QUERY_STRING = "\n(comment) @comment\n(block\n  . (expression_statement\n    (string)) @docstring)\n(module\n  . (expression_statement\n    (string)) @docstring)\n"
query = Query(PY_LANGUAGE, QUERY_STRING)
cursor = QueryCursor(query)


def should_preserve_comment(content: str) -> bool:
    content = content.strip()
    return any((content.startswith(p) for p in ["#!", "# type:", "# fmt:"]))


def strip_file(file_path) -> None:
    try:
        source_code = Path(file_path).read_text(encoding="utf-8")
        source_bytes = bytes(source_code, "utf8")
        tree = parser.parse(source_bytes)
        captures = cursor.captures(tree.root_node)
        modifications = []
        for node, tag in captures:
            if tag == "comment":
                comment_text = source_code[node.start_byte : node.end_byte]
                if not should_preserve_comment(comment_text):
                    modifications.append((node.start_byte, node.end_byte, ""))
            elif tag == "docstring":
                parent = node.parent
                if parent and parent.named_child_count == 1:
                    modifications.append((node.start_byte, node.end_byte, "pass"))
                else:
                    modifications.append((node.start_byte, node.end_byte, ""))
        if not modifications:
            return
        modifications.sort(key=operator.itemgetter(0), reverse=True)
        working_code = source_code
        for start, end, replacement in modifications:
            working_code = working_code[:start] + replacement + working_code[end:]
        try:
            ast.parse(working_code)
            Path(file_path).write_text(working_code, encoding="utf-8")
        except SyntaxError:
            pass
    except Exception as e:
        print(f"Error processing {file_path}: {e}")


def main() -> None:
    files = [os.path.join(r, f) for r, _, fs in os.walk(".") for f in fs if f.endswith(".py")]
    if not files:
        return
    print(f"Processing {len(files)} files using QueryCursor...")
    with multiprocessing.get_context("spawn").Pool(8) as pool:
        pool.map(strip_file, files)
    print("In-place cleanup complete.")


if __name__ == "__main__":
    main()
