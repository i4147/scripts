import re
import sys
from pathlib import Path


def parse_tree_file(tree_path: str):
    with Path(tree_path).open("r", encoding="utf-8") as f:
        lines = f.readlines()
    lines = [line.rstrip() for line in lines if line.strip()]
    root_line = lines[0].strip() if lines else ""
    root_name = re.sub("[├└│─]+", "", root_line).strip().rstrip("/")
    root_parts = [root_name] if root_name else []
    entries = []
    stack = [(0, root_parts)]
    for line in lines[1:]:
        if not line.strip():
            continue
        match = re.match("^([├└│ ]*)([├└]──\\s*)?(\\S.*)$", line)
        if not match:
            continue
        prefix, _marker, name = match.groups()
        name = name.strip()
        if name.startswith("#") or name == "":
            continue
        indent = len(prefix) // 4
        while stack and stack[-1][0] >= indent:
            stack.pop()
        current_path = stack[-1][1] if stack else []
        is_dir = name.endswith("/") or "." not in Path(name).name or any((c in name for c in ["/", "\\"]))
        name = name.rstrip("/")
        full_path = [*current_path, name]
        entries.append((indent, full_path, is_dir))
        if is_dir:
            stack.append((indent, full_path))
    return entries


def create_tree_from_entries(entries) -> None:
    created_dirs = set()
    for _indent, path_parts, is_dir in entries:
        if len(path_parts) == 1 and path_parts[0] == "dictionary-webapp":
            continue
        path = Path(*path_parts)
        if is_dir:
            path.mkdir(parents=True, exist_ok=True)
            created_dirs.add(str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()


def main() -> None:
    tree_file = sys.argv[1]
    if not Path(tree_file).exists():
        print(f"❌ Error: '{tree_file}' not found in current directory.")
        return
    print(f"📖 Parsing '{tree_file}'...")
    entries = parse_tree_file(tree_file)
    if not entries:
        print("⚠️  No valid entries found in tree file.")
        return
    print(f"✅ Parsed {len(entries)} entries.")
    print("📁 Creating folder structure...")
    create_tree_from_entries(entries)
    print("✨ Done! Folder structure created successfully.")


if __name__ == "__main__":
    main()
