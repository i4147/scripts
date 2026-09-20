import ast
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path


def get_source(node, content):
    return ast.get_source_segment(content, node)


def normalize_source(source):
    if not source:
        return ""
    return "\n".join(line.rstrip() for line in source.strip().splitlines())


def analyze_files():
    cwd = Path.cwd()
    target_dirs = [cwd]
    definitions = defaultdict(list)
    source_map = {}

    for target_dir in target_dirs:
        for root, dirs, files in os.walk(target_dir):
            if ".git" in dirs:
                dirs.remove(".git")
            for file in files:
                if file.endswith(".py"):
                    file_path = Path(root) / file
                    try:
                        content = file_path.read_text(encoding="utf-8")
                        tree = ast.parse(content)
                        for node in tree.body:
                            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                                source = get_source(node, content)
                                norm = normalize_source(source)
                                key = (type(node).__name__, node.name, norm)
                                definitions[key].append(str(file_path))
                                if key not in source_map:
                                    source_map[key] = source
                            elif isinstance(node, ast.Assign):
                                for target in node.targets:
                                    if isinstance(target, ast.Name):
                                        source = get_source(node, content)
                                        norm = normalize_source(source)
                                        key = ("Constant", target.id, norm)
                                        definitions[key].append(str(file_path))
                                        if key not in source_map:
                                            source_map[key] = source
                    except Exception:
                        continue

    repeated = []
    for key, paths in definitions.items():
        if len(set(paths)) > 5:
            repeated.append(
                {
                    "type": key[0],
                    "name": key[1],
                    "source": source_map[key],
                    "count": len(set(paths)),
                    "files": list(set(paths)),
                }
            )

    return repeated


if __name__ == "__main__":
    repeated = analyze_files()
    repeated.sort(key=lambda x: x["count"], reverse=True)

    with open("repeated.json", "w") as f:
        json.dump(repeated, f, indent=2, ensure_ascii=False)
