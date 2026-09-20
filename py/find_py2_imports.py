import sys
from pathlib import Path

import tree_sitter_python as tsp
from dh import STDLIB2, get_filez
from rapidfuzz import fuzz
from termcolor import cprint
from tree_sitter import Language, Parser

cwd = Path.cwd()
parser = Parser()
parser.language = Language(tsp.language())
VALID = {
    "import_statement",
    "import_from_statement",
}


def process_file(fp: Path) -> None:
    src = fp.read_bytes()
    tree = parser.parse(src)
    root = tree.root_node
    impoz = []
    results = [src[node.start_byte : node.end_byte].decode() for node in root.children if node.type in VALID]
    if results:
        for k in results:
            if k.startswith("import "):
                k = k.replace("import ", "")
                if " as " in k:
                    indx = k.index(" as ")
                    k = k[:indx]
                if "." in k:
                    indx = k.index(".")
                    k = k[:indx]
                if k not in impoz and not k.startswith("_"):
                    impoz.append(k + "\n")
            elif k.startswith("from "):
                k = k.replace("from ", "")
                if k.startswith("."):
                    continue
                if " as " in k:
                    indx = k.index(" as ")
                    k = k[:indx]
                if "." in k:
                    indx = k.index(".")
                    k = k[:indx]
                if " import" in k:
                    indx = k.index(" import")
                    k = k[:indx]
                if k not in impoz and not k.startswith("_"):
                    impoz.append(k + "\n")
    impoz = sorted(set(impoz))
    stdlib2 = list(STDLIB2)
    for x in impoz:
        if x in STDLIB2:
            if x not in {"io", "os", "pathlib", "ast"}:
                cprint(f"{fp.relative_to(cwd)} {x}", "green")
                continue
        for v in stdlib2:
            x = x.strip()
            ratio = fuzz.ratio(x, v)
            if ratio > 85 and len(x) > 3 and len(v) > 3:
                if not x in {"io", "os", "pathlib"}:
                    cprint(f"{fp.relative_to(cwd)}/{x}/{v}/{ratio}", "cyan")
                    continue


def main() -> None:
    for path in get_filez(cwd):
        if path.is_symlink():
            continue
        if path.suffix == ".py":
            process_file(path)


if __name__ == "__main__":
    sys.exit(main())
