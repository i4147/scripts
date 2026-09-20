import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from itertools import chain
from pathlib import Path
from token import NAME
from tokenize import generate_tokens


class ImportParseException(Exception):
    pass


def parse_import(line):
    try:
        from_, module, import_, rest = line.split(None, 3)
    except ValueError:
        raise ImportParseException(line)

    if (from_, import_) != ("from", "import"):
        raise ImportParseException(line)

    symbols = [s.strip() for s in rest.split(",")]
    return module, symbols


def parse_splat_import(line):
    try:
        import_, rest = line.split(None, 1)
        assert import_ == "import"
    except (ValueError, AssertionError):
        raise ImportParseException(line)

    return set((s.strip() for s in rest.split(",")))


class DefaultDict(dict):
    def __init__(self, default=None) -> None:
        self.default = default

    def __getitem__(self, key):
        if key in self:
            return self.get(key)
        else:
            return self.setdefault(key, deepcopy(self.default))


def gather_imports(lines):
    imports = DefaultDict(set())
    splats = set()
    prev = ""

    for line in lines:
        if prev:
            line = prev + line
            prev = ""

        if line.endswith("\\"):
            prev = line[:-1]
            continue

        if not line.strip():
            continue

        try:
            module, symbols = parse_import(line)
        except ImportParseException:
            splats |= parse_splat_import(line)
        else:
            for s in symbols:
                imports[module].add(s)

    return imports, splats


def used_symbols(lines, bskip=0, eskip=float("inf")) -> set[str]:
    liter = iter(lines)

    def readline():
        return next(liter) + "\n"

    used = set(("*",))
    for ttype, token, begin, end, _ in generate_tokens(readline):
        row = begin[0] - 1
        if bskip <= row <= eskip:
            continue
        if ttype == NAME:
            used.add(token)
    return used


def split_import(imp):
    try:
        _, _, symbol = imp.split(None, 2)
        yield symbol
    except ValueError:
        yield imp.split(".")[0]


def cull_unused(used: set[str], imports) -> None:
    remove = set()
    for imp in imports:
        for s in split_import(imp):
            if s not in used:
                remove.add(imp)
                break
    imports -= remove


def add_wrapped_import(output: list[str], module, symbols, maxlen=78) -> None:
    lower_syms = []
    upper_syms = []
    other_syms = []

    for s in symbols:
        if s.islower():
            lower_syms.append(s)
        elif s.isupper():
            upper_syms.append(s)
        else:
            other_syms.append(s)

    line = f"from {module} import "
    for s in chain(sorted(lower_syms), sorted(other_syms, key=str.lower), sorted(upper_syms)):
        if len(line) + len(s) > maxlen:
            output.append(line[:-2])
            line = f"from {module} import {s}, "
        else:
            line += f"{s}, "

    if line:
        output.append(line[:-2])


def format_imports(imports: DefaultDict, splats) -> list[str]:
    new = [f"import {s}" for s in sorted(splats)]
    for module, symbols in sorted(imports.items()):
        if symbols:
            add_wrapped_import(new, module, symbols)
    return new


def cleanup_imports(input_lines):
    used_tokens = used_symbols(input_lines)
    imports, splats = gather_imports(input_lines)

    
    original_imports = deepcopy(imports)
    original_splats = deepcopy(splats)

    cull_unused(used_tokens, splats)
    for module in list(imports.keys()):
        cull_unused(used_tokens, imports[module])

    
    removed = set()
    for module in original_imports:
        for imp in original_imports[module]:
            if imp not in imports.get(module, set()):
                removed.add(f"from {module} import {imp}")
    for imp in original_splats:
        if imp not in splats:
            removed.add(f"import {imp}")

    cleaned = format_imports(imports, splats)
    return cleaned, removed


def process_file(path: Path):
    path = Path(path)
    with open(path, "r") as f:
        lines = f.readlines()

    import_lines = []
    non_import_lines = []
    in_import_section = True

    for line in lines:
        stripped = line.strip()
        if in_import_section and (stripped.startswith(("import ", "from ")) or not stripped):
            import_lines.append(line)
        else:
            in_import_section = False
            non_import_lines.append(line)

    cleaned_imports, removed = cleanup_imports(import_lines)

    with open(path, "w") as f:
        f.writelines(cleaned_imports)
        if cleaned_imports and non_import_lines:
            f.write("\n")
        f.writelines(non_import_lines)

    return path, removed


def collect_py_files(directory: Path):
    return list(Path(directory).rglob("*.py")) - list(Path(directory).rglob("__init__.py"))


def main() -> None:
    if len(sys.argv) > 2:
        print("Usage: python cleanup_imports.py [file_or_directory]")
        sys.exit(1)

    target = Path(sys.argv[1]) if len(sys.argv) == 2 else Path.cwd()

    if target.is_file():
        if target.suffix == ".py" and target.name != "__init__.py":
            path, removed = process_file(target)
            if removed:
                print(f"\nFile: {path}")
                print("Removed imports:")
                for imp in sorted(removed):
                    print(f"  - {imp}")
        else:
            print(f"Skipping non-Python or __init__.py file: {target}")
    elif target.is_dir():
        py_files = collect_py_files(target)
        if not py_files:
            print(f"No Python files found in: {target}")
            return

        print(f"Processing {len(py_files)} Python files in parallel...")
        with ProcessPoolExecutor() as executor:
            futures = {executor.submit(process_file, file): file for file in py_files}
            for future in as_completed(futures):
                path, removed = future.result()
                if removed:
                    print(f"\nFile: {path}")
                    print("Removed imports:")
                    for imp in sorted(removed):
                        print(f"  - {imp}")
    else:
        print(f"Error: '{target}' is not a valid file or directory.")
        sys.exit(1)


if __name__ == "__main__":
    main()
