import sys
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
    for ttype, token, begin, end, line in generate_tokens(readline):
        row = begin[0] - 1
        if bskip <= row <= eskip:
            continue
        if ttype == NAME:
            used.add(token)
    return used


def split_import(imp):
    try:
        dummy, as_, symbol = imp.split(None, 2)
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


def add_wrapped_import(output, module, symbols, maxlen=78) -> None:
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

    line = "from %s import " % module

    def stricmp(a, b):
        return (a.lower() > b.lower()) - (a.lower() < b.lower())

    for s in chain(sorted(lower_syms), sorted(other_syms, key=str.lower), sorted(upper_syms)):
        line = line or "from %s import " % module
        if len(line) + len(s) > maxlen:
            output.append(line[:-2])
            line = "from %s import %s, " % (module, s)
        else:
            line += s + ", "

    if line:
        output.append(line[:-2])


def format_imports(imports: DefaultDict, splats):
    new = ["import " + s for s in sorted(splats)]
    for module, symbols in sorted(imports.items()):
        if symbols:
            add_wrapped_import(new, module, symbols)
    return new


def cleanup_imports(input_lines: list[str]):
    used_tokens = used_symbols(input_lines)
    imports, splats = gather_imports(input_lines)

    cull_unused(used_tokens, splats)
    for i in imports.values():
        cull_unused(used_tokens, i)

    return format_imports(imports, splats)


def main() -> None:
    filename = Path(sys.argv[1])
    content = filename.read_text(encoding="utf-8")
    input_lines = content.splitlines(keepends=True)
    cleaned_imports = cleanup_imports(input_lines)
    for line in cleaned_imports:
        print(line)
    outf = filename.with_name(filename.stem + "_cleaned" + filename.suffix)
    outf.write_text("".join(cleaned_imports), encoding="utf-8")
    print(f"{outf.name} created.")


if __name__ == "__main__":
    main()
