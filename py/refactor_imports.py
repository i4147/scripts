from __future__ import annotations

import ast
import collections
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import astor

REPEATED_JSON_PATH = Path("repeated.json")


def load_refactoring_maps():
    with open(REPEATED_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    file_to_objects = collections.defaultdict(list)
    for item in data:
        obj_name = item["name"]
        for path_str in item["files"]:
            p = Path(path_str)
            file_to_objects[p.name].append(obj_name)
    return file_to_objects


class ASTStripper(ast.NodeTransformer):
    def __init__(self, target_names):
        super().__init__()
        self.target_names = set(target_names)
        self.removed_something = False

    def visit_FunctionDef(self, node):
        if node.name in self.target_names:
            self.removed_something = True
            return None
        return self.generic_visit(node)

    def visit_ClassDef(self, node):
        if node.name in self.target_names:
            self.removed_something = True
            return None
        return self.generic_visit(node)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in self.target_names:
                self.removed_something = True
                return None
        return self.generic_visit(node)


def refactor_single_file(path: Path, objects_to_remove: list):
    try:
        source_code = path.read_text(encoding="utf-8")
        tree = ast.parse(source_code)
    except Exception as e:
        print(f"❌ Error parsing {path.name}: {e}")
        return
    stripper = ASTStripper(objects_to_remove)
    modified_tree = stripper.visit(tree)
    ast.fix_missing_locations(modified_tree)
    if not stripper.removed_something:
        print(f"➖ No matching structural nodes found inside {path.name}")
        return
    import_names = ", ".join(sorted(objects_to_remove))
    import_statement = f"from dh import {import_names}\n"
    try:
        cleaned_source = astor.to_source(modified_tree)
    except Exception as e:
        print(f"❌ Failed to stringify AST for {path.name}: {e}")
        return
    lines = cleaned_source.splitlines(keepends=True)
    insert_idx = 0
    if lines and lines[0].startswith("#!"):
        insert_idx = 1
    if len(lines) > insert_idx and (
        lines[insert_idx].strip().startswith('"""') or lines[insert_idx].strip().startswith("'''")
    ):
        insert_idx += 1
    lines.insert(insert_idx, import_statement)
    try:
        path.write_text("".join(lines), encoding="utf-8")
        print(f"✅ Refactored {path.name}: Stripped {objects_to_remove} -> added 'dh' import")
    except Exception as e:
        print(f"❌ Error writing updates back to {path.name}: {e}")


def main():
    if not REPEATED_JSON_PATH.exists():
        print(f"Error: {REPEATED_JSON_PATH.name} not found in the current directory.")
        return
    refactor_map = load_refactoring_maps()
    current_dir = Path(".")
    local_files = {f.name: f for f in current_dir.glob("*.py")}
    tasks = []
    for filename, objects in refactor_map.items():
        if filename in local_files:
            tasks.append((local_files[filename], objects))
    if not tasks:
        print("No matching files found in the current directory to refactor.")
        return
    print(f"🚀 Found {len(tasks)} files to clean structural code from. Starting parallel processing...")
    with ThreadPoolExecutor() as executor:
        for path, objects in tasks:
            executor.submit(refactor_single_file, path, objects)
    print("🎉 Structural refactoring complete! All duplicate bodies stripped.")


if __name__ == "__main__":
    raise SystemExit(main())
