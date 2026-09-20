import ast
import hashlib
import sys
from collections import defaultdict
from pathlib import Path

CURRENT_DIR = Path()
UTILS_FILE = CURRENT_DIR / "utils.py"
TOP_LEVEL_NODES = (ast.FunctionDef, ast.ClassDef, ast.Assign)
CONSTANT_NODES = (ast.Assign,)


def is_simple_constant(node: ast.Assign) -> bool:
    if len(node.targets) != 1:
        return False
    target = node.targets[0]
    if not isinstance(target, ast.Name):
        return False
    value = node.value
    if isinstance(value, (ast.Constant, ast.Name)):
        return True
    return bool(isinstance(value, ast.UnaryOp) and isinstance(value.operand, (ast.Constant, ast.Name)))


def get_name(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign):
        if len(node.targets) > 0 and isinstance(node.targets[0], ast.Name):
            return node.targets[0].id
        if isinstance(node.targets[0], (ast.Tuple, ast.List)):
            return ""
    return ""


def node_to_source(node: ast.AST, source_lines: list[str]) -> str:
    start_line = node.lineno - 1
    end_line = node.end_lineno if hasattr(node, "end_lineno") and node.end_lineno else start_line + 1
    if end_line <= start_line:
        end_line = start_line + 1
    return "\n".join(source_lines[start_line:end_line])


def hash_node(node: ast.AST, source_lines: list[str]) -> str:
    src = node_to_source(node, source_lines)
    normalized = "\n".join((line.rstrip() for line in src.splitlines())).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def collect_definitions(file_path: Path) -> list[tuple[str, str, ast.AST]]:
    try:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        try:
            _ = ast.parse(source)
        except:
            print(f"{file_path} ast parse error")
            sys.exit(1)
        source_lines = source.splitlines()
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        print(f"[WARN] Syntax error in {file_path}: {e}")
        return []
    definitions = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
            h = hash_node(node, source_lines)
            definitions.append((name, h, node))
        elif isinstance(node, ast.Assign) and is_simple_constant(node):
            name = get_name(node)
            if name:
                h = hash_node(node, source_lines)
                definitions.append((name, h, node))
    return definitions


def ensure_utils_file() -> bool:
    if not UTILS_FILE.exists():
        UTILS_FILE.write_text("# Auto-generated utilities from deduplication\n\n")
        return True
    content = UTILS_FILE.read_text()
    if "# Auto-generated" not in content:
        UTILS_FILE.write_text("# Auto-generated utilities from deduplication\n\n" + content)
    return False


def get_imports_from_file(file_path: Path) -> list[str]:
    try:
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []
    imports = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            imports.append(line.rstrip())
    return imports


def add_import_to_file(file_path: Path, new_import: str) -> None:
    try:
        with open(file_path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return
    insert_pos = 0
    for i, line in enumerate(lines):
        if line.startswith(("#!", "# -*- coding:")) or (line.strip().startswith("#") and insert_pos == i):
            insert_pos = i + 1
        else:
            break
    if not new_import.endswith("\n"):
        new_import += "\n"
    lines.insert(insert_pos, new_import)
    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def remove_definition_from_file(file_path: Path, node: ast.AST, source_lines: list[str]) -> None:
    start_line = node.lineno - 1
    end_line = node.end_lineno if hasattr(node, "end_lineno") and node.end_lineno else start_line + 1
    new_lines = source_lines[:start_line] + source_lines[end_line:]
    if start_line > 0 and new_lines[start_line - 1].strip() == "":
        pass
    elif start_line > 0:
        new_lines.insert(start_line, "\n")
    if start_line < len(new_lines) and new_lines[start_line].strip() == "":
        pass
    elif start_line < len(new_lines):
        new_lines.insert(start_line + 1, "\n")
    try:
        _ = ast.parse(new_lines)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines).rstrip() + "\n")
    except:
        print(f"{file_path} ast parse error")


def main() -> None:
    py_files = list(CURRENT_DIR.rglob("*.py"))
    py_files = [f for f in py_files if f.name not in {"utils.py", "dedupe.py"}]
    hash_to_defs: dict[str, list[tuple[Path, str, ast.AST, list[str]]]] = defaultdict(list)
    for fpath in py_files:
        defs = collect_definitions(fpath)
        for name, h, node in defs:
            with open(fpath, encoding="utf-8") as f:
                source_lines = f.read().splitlines()
            hash_to_defs[h].append((fpath, name, node, source_lines))
    duplicates_found = False
    for h, items in hash_to_defs.items():
        if len(items) <= 1:
            continue
        duplicates_found = True
        canonical_file, canonical_name, canonical_node, _ = items[0]
        duplicates = items[1:]
        ensure_utils_file()
        utils_content = UTILS_FILE.read_text()
        print(f"Found duplicate: {canonical_name} ({len(items)} occurrences)")
        for dup_file, name, node, _ in duplicates:
            dup_src = node_to_source(node, dup_file.read_text().splitlines())
            print(f"  → Moving `{name}` from {dup_file} →.py")
            if not utils_content.endswith("\n\n"):
                utils_content += "\n\n"
            utils_content += dup_src.rstrip() + "\n\n"
            UTILS_FILE.write_text(utils_content)
    if not duplicates_found:
        print("No duplicate definitions found.")
    else:
        print("  - Duplicates moved to `utils.py`")


if __name__ == "__main__":
    main()
