
from tree_sitter import Tree
import sys
from pathlib import Path

import tree_sitter_python as tsp
from dh import STDLIB, cprint, get_installed_pkgs, get_pyfiles
from tree_sitter import Language, Parser

parser = Parser()
parser.language = Language(tsp.language())
VALID = {"import_statement", "import_from_statement"}


def mpf3(process_function: Callable, files: list[Path], **kwargs):

    return Parallel(n_jobs=-1)((delayed(process_function)(file, **kwargs) for file in files))


def extract_file(src: bytes, tree: Tree) -> list[str]:
    root = tree.root_node
    return [src[node.start_byte : node.end_byte].decode() for node in root.children if node.type in VALID]


def process_file(fp) -> list[str]:
    src = fp.read_bytes()
    tree = parser.parse(src)
    return extract_file(src, tree)


def main() -> None:
    outfile = Path("importz.txt")
    all_imports = []
    seen = set()
    cwd = Path.cwd()
    pyfiles = get_pyfiles(cwd)
    allpyfiles = len(pyfiles)
    cprint(f"{allpyfiles} python files found", "green")
    c = 0
    results = mpf3(process_file, pyfiles)
    for result in results:
        if result:
            for k in result:
                if k not in seen:
                    seen.add(k)
                    all_imports.append(k)
    all_imports = sorted(all_imports)
    outfile.write_text("\n".join(all_imports), encoding="utf-8")
    content = outfile.read_text(encoding="utf-8")
    impoz = []
    for line in content.splitlines():
        line = line.lower()
        if line.startswith("import "):
            line = line.replace("import ", "")
            if " as " in line:
                indx = line.index(" as ")
                line = line[:indx]
            if "." in line:
                indx = line.index(".")
                line = line[:indx]
            if line not in impoz and (not line.startswith("_")):
                impoz.append(line + "\n")
        elif line.startswith("from "):
            line = line.replace("from ", "")
            if line.startswith("."):
                continue
            if " as " in line:
                indx = line.index(" as ")
                line = line[:indx]
            if "." in line:
                indx = line.index(".")
                line = line[:indx]
            if " import" in line:
                indx = line.index(" import")
                line = line[:indx]
            if line not in impoz and (not line.startswith("_")):
                impoz.append(line + "\n")
    impoz = sorted(set(impoz))
    stdlib_plus_installed = list(STDLIB)
    inpkg = [p.replace("-", "_").lower() for p in get_installed_pkgs()]
    stdlib_plus_installed.extend(inpkg)
    filterd = []
    for rq in impoz:
        if rq.strip() not in stdlib_plus_installed:
            print(rq.strip())
            filterd.append(rq)
    outfile.write_text("\n".join(filterd), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())




