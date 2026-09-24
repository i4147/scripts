import argparse
import ast
import os
import sys
from pathlib import Path


def extract_imports(source):
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"Syntax error in file: {e}")

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({"type": "import", "module": alias.name, "asname": alias.asname, "line": node.lineno})
        elif isinstance(node, ast.ImportFrom):
            module = node.module
            for alias in node.names:
                if alias.name == "*":
                    imports.append({"type": "from", "module": module, "name": "*", "asname": None, "line": node.lineno})
                else:
                    imports.append(
                        {
                            "type": "from",
                            "module": module,
                            "name": alias.name,
                            "asname": alias.asname,
                            "line": node.lineno,
                        }
                    )
    return imports


def get_used_names(source):
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"Syntax error in file: {e}")

    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                used.add(node.value.id)
    return used


def find_unused_imports(source):
    imports = extract_imports(source)
    used_names = get_used_names(source)

    unused = []
    for imp in imports:
        if imp["type"] == "import":
            name = imp["asname"] if imp["asname"] else imp["module"].split(".")[0]
            if name not in used_names:
                unused.append(imp)
        elif imp["type"] == "from":
            if imp["name"] == "*":
                continue
            name = imp["asname"] if imp["asname"] else imp["name"].split(".")[0]
            if name not in used_names:
                unused.append(imp)
    return unused, imports


def format_import(imp):
    if imp["type"] == "import":
        if imp["asname"]:
            return f"Line {imp['line']}: import {imp['module']} as {imp['asname']}"
        else:
            return f"Line {imp['line']}: import {imp['module']}"
    elif imp["type"] == "from":
        if imp["name"] == "*":
            return f"Line {imp['line']}: from {imp['module']} import *"
        elif imp["asname"]:
            return f"Line {imp['line']}: from {imp['module']} import {imp['name']} as {imp['asname']}"
        else:
            return f"Line {imp['line']}: from {imp['module']} import {imp['name']}"


def process_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except (UnicodeDecodeError, PermissionError) as e:
        return str(filepath), [], str(e)

    try:
        unused, _ = find_unused_imports(source)
    except ValueError as e:
        return str(filepath), [], str(e)

    unused_str = [format_import(imp) for imp in unused]
    return str(filepath), unused_str, None


def process_directory(directory):
    results = {}
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                filepath = Path(root) / file
                filename, unused, error = process_file(filepath)
                if unused or error:
                    results[filename] = {"unused": unused, "error": error}
    return results


def main():
    parser = argparse.ArgumentParser(description="Find unused imports in Python files or directories.")
    parser.add_argument("path", nargs="+", help="Python file(s) or directory(ies) to analyze")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only show files with unused imports or errors")
    args = parser.parse_args()

    for path in args.path:
        path_obj = Path(path)
        if path_obj.is_file():
            filename, unused, error = process_file(path_obj)
            if error:
                print(f"{filename}: Error - {error}", file=sys.stderr)
            elif unused:
                print(f"\n{filename}")
                print("Unused imports:")
                for imp in unused:
                    print(f"  {imp}")
            elif not args.quiet:
                print(f"{filename}: No unused imports")
        elif path_obj.is_dir():
            results = process_directory(path_obj)
            for filename, data in results.items():
                if data["error"]:
                    print(f"{filename}: Error - {data['error']}", file=sys.stderr)
                elif data["unused"]:
                    print(f"\n{filename}")
                    print("Unused imports:")
                    for imp in data["unused"]:
                        print(f"  {imp}")
        else:
            print(f"Path not found: {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
