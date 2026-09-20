
import ast
import re
from pathlib import Path
from multiprocessing import Pool
from typing import Optional, Tuple
import sys

RE_FUNCTIONS = {
    "compile",
    "search",
    "match",
    "fullmatch",
    "split",
    "findall",
    "finditer",
    "sub",
    "subn",
    "escape",
    "purge",
    "Pattern",
}
RE_CALL_PATTERN = re.compile("\\bre\\.(" + "|".join(RE_FUNCTIONS) + ")\\s*\\(", re.IGNORECASE)


def needs_raw_string(string_content: str) -> bool:
    escape_sequences = re.findall("\\\\[\\\\abfnrtv\"\\']", string_content)
    escape_count = len(escape_sequences)
    regex_indicators = [
        "\\d",
        "\\w",
        "\\s",
        "\\S",
        "\\W",
        "\\D",
        "\\[",
        "\\]",
        "\\(",
        "\\)",
        "\\|",
        "\\^",
        "\\$",
        "\\+",
        "\\*",
        "\\?",
        "\\{",
        "\\}",
        "\\.",
        "\\b",
        "\\B",
    ]
    has_regex_pattern = any((pattern in string_content for pattern in regex_indicators))
    return escape_count >= 2 or (escape_count >= 1 and has_regex_pattern)


def extract_and_convert_strings(content: str) -> Optional[str]:
    original_content = content
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    string_positions = {}

    class StringVisitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Attribute):
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "re"
                    and (node.func.attr in RE_FUNCTIONS)
                ):
                    if node.args:
                        arg = node.args[0]
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            string_positions[arg.end_col_offset] = {
                                "value": arg.value,
                                "lineno": arg.lineno,
                                "col_offset": arg.col_offset,
                                "end_col": arg.end_col_offset,
                            }
            self.generic_visit(node)

    visitor = StringVisitor()
    visitor.visit(tree)
    if not string_positions:
        return None
    lines = content.split("\n")
    converted = False
    for end_col, info in string_positions.items():
        string_val = info["value"]
        lineno = info["lineno"] - 1
        if needs_raw_string(string_val):
            line = lines[lineno]
            col_offset = info["col_offset"]
            end_col_offset = info["end_col"]
            original_literal = line[col_offset:end_col_offset]
            if original_literal.startswith('"""') or original_literal.startswith("'''"):
                continue
            quote_char = original_literal[0]
            if original_literal.startswith(('r"', "r'", 'r"""', "r'''")):
                continue
            try:
                unescaped = string_val
                new_literal = f"r{quote_char}{unescaped}{quote_char}"
                new_line = line[:col_offset] + new_literal + line[end_col_offset:]
                lines[lineno] = new_line
                converted = True
            except Exception:
                continue
    if not converted:
        return None
    return "\n".join(lines)


def validate_python_file(content: str) -> bool:
    try:
        ast.parse(content)
        return True
    except SyntaxError as e:
        print(f"  ✗ Syntax error: {e}", file=sys.stderr)
        return False


def process_file(filepath: Path) -> Tuple[Path, bool, str]:
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return (filepath, False, f"Failed to read: {e}")
    converted_content = extract_and_convert_strings(content)
    if converted_content is None:
        return (filepath, True, "No changes needed")
    if not validate_python_file(converted_content):
        return (filepath, False, "Validation failed, skipping")
    try:
        filepath.write_text(converted_content, encoding="utf-8")
        return (filepath, True, "✓ Converted and saved")
    except Exception as e:
        return (filepath, False, f"Failed to write: {e}")


def main():
    current_dir = Path.cwd()
    python_files = list(current_dir.rglob("*.py"))
    if not python_files:
        print("No Python files found in current directory")
        return
    print(f"Found {len(python_files)} Python files")
    print(f"Processing with parallel workers...")
    print(f"Target re functions: {', '.join(sorted(RE_FUNCTIONS))}\n")
    with Pool() as pool:
        results = pool.map(process_file, python_files)
    successful = sum((1 for _, success, _ in results if success))
    changed = sum((1 for _, success, msg in results if success and "✓" in msg))
    print("\n" + "=" * 70)
    for filepath, success, message in results:
        status = "✓" if success else "✗"
        rel_path = filepath.relative_to(current_dir)
        print(f"{status} {rel_path}: {message}")
    print("=" * 70)
    print(f"\nSummary: {successful}/{len(python_files)} processed successfully")
    print(f"         {changed} files converted")


if __name__ == "__main__":
    main()
