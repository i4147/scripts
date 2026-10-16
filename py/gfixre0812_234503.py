import ast
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor


class RegexRawConverter(ast.NodeTransformer):
    def __init__(self, source_lines):
        self.source_lines = source_lines
        self.modified = False

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("compile", "match", "search", "sub", "findall"):
            if node.args and isinstance(node.args[0], ast.Constant):
                const = node.args[0]
                if isinstance(const.value, str) and "\\" in const.value:
                    line = self.source_lines[const.lineno - 1]
                    if "\\\\" in line:
                        self.modified = True
        return self.generic_visit(node)


def process_file(file_path: Path):
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        converter = RegexRawConverter(content.split("\n"))
        converter.visit(tree)

        if converter.modified:
            print(f"⚠️  {file_path.name} needs manual review for safe conversion")
    except SyntaxError:
        print(f"❌ {file_path.name}: syntax error")


def main():
    py_files = list(Path(".").rglob("*.py"))
    py_files = [f for f in py_files if f.is_file() and f.name != Path(__file__).name]

    with ThreadPoolExecutor() as executor:
        executor.map(process_file, py_files)


if __name__ == "__main__":
    main()
