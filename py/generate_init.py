import ast
import sys
from pathlib import Path


def get_public_names(file_path: Path) -> list[str]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except SyntaxError as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
        return []
    public_names = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                public_names.append(node.name)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            public_names.append(node.name)
    return sorted(set(public_names))


def get_python_modules(directory: Path) -> list[Path]:
    modules = []
    for file_path in directory.glob("*.py"):
        if file_path.name != "__init__.py" and (not file_path.name.startswith("_")):
            modules.append(file_path)
    return sorted(modules)


def generate_init_content(modules: list[Path]) -> str:
    lines = []
    all_exports = []
    for module in modules:
        module_name = module.stem
        public_names = get_public_names(module)
        if public_names:
            names_str = ", ".join(public_names)
            lines.append(f"from .{module_name} import {names_str}")
            all_exports.extend(public_names)
    if all_exports:
        lines.append("")
        all_str = ", ".join(repr(name) for name in all_exports)
        lines.append(f"__all__ = [{all_str}]")
    if lines:
        lines.append("")
    return "\n".join(lines)


def main():
    cwd = Path.cwd()
    print(f"Scanning directory: {cwd}")
    modules = get_python_modules(cwd)
    if not modules:
        print("No Python modules found in the current directory.")
        return
    print(f"Found {len(modules)} Python module(s):")
    for module in modules:
        public_names = get_public_names(module)
        print(f"  - {module.name}: {len(public_names)} public name(s)")
    init_content = generate_init_content(modules)
    init_file = cwd / "__init__.py"
    if init_file.exists():
        response = input(f"\n{init_file} already exists. Overwrite? (y/N): ")
        if response.lower() != "y":
            print("Aborted.")
            return
    with open(init_file, "w", encoding="utf-8") as f:
        f.write(init_content)
    print(f"\nCreated {init_file}")
    print("\nGenerated content:")
    print("-" * 40)
    print(init_content)
    print("-" * 40)


if __name__ == "__main__":
    raise SystemExit(main())
