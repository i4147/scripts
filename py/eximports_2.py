from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import tree_sitter_python as tsp
from dh import cprint, get_installed_pkgs
from tree_sitter import Language, Parser

parser = Parser()
parser.language = Language(tsp.language())
VALID = {"import_statement", "import_from_statement"}


def process_file(path: Path) -> list[str]:
    path = Path(path)
    src = path.read_bytes()
    tree = parser.parse(src)
    root = tree.root_node
    return [src[node.start_byte : node.end_byte].decode() for node in root.children if node.type in VALID]


def normalize_import(import_line: str) -> str | None:
    line = import_line.lower().strip()
    if line.startswith("import "):
        module = line[7:]
        if " as " in module:
            module = module[: module.index(" as ")]
        if "." in module:
            module = module[: module.index(".")]
        return module if module and not module.startswith("_") else None
    elif line.startswith("from "):
        module = line[5:]
        if module.startswith("."):
            return None
        if " import" in module:
            module = module[: module.index(" import")]
        if " as " in module:
            module = module[: module.index(" as ")]
        if "." in module:
            module = module[: module.index(".")]
        return module if module and not module.startswith("_") else None
    return None


def process_files_parallel(files: list[Path]) -> set[str]:
    all_imports = set()
    with ProcessPoolExecutor() as executor:
        future_to_file = {executor.submit(process_file, path): path for path in files}
        for future in as_completed(future_to_file):
            try:
                imports = future.result()
                all_imports.update(imports)
            except Exception as e:
                path = future_to_file[future]
                cprint(f"Error processing {path}: {e}", "yellow")
    return all_imports


def filter_imports(imports: set[str]) -> list[str]:
    stdlib_set = set(STDLIB)
    installed_pkgs = {pkg.replace("-", "_").lower() for pkg in get_installed_pkgs()}
    excluded = stdlib_set | installed_pkgs
    filtered = []
    for imp in imports:
        normalized = normalize_import(imp)
        if normalized and normalized not in excluded:
            filtered.append(normalized + "\n")
    return sorted(set(filtered))


def main() -> None:
    outfile = Path("importz.txt")
    cwd = Path.cwd()
    pyfiles = get_pyfiles(cwd)
    cprint(f"{len(pyfiles)} python files found", "green")
    all_imports = process_files_parallel(pyfiles)
    filtered_imports = filter_imports(all_imports)
    outfile.write_text("".join(filtered_imports), encoding="utf-8")
    for imp in filtered_imports:
        print(imp.strip())


if __name__ == "__main__":
    raise SystemExit(main())
