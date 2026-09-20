import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import tree_sitter_python as tsp
from dh import get_pyfiles
from tree_sitter import Language, Parser

OUTPUT_DIR = Path("output")
parser = Parser()
parser.language = Language(tsp.language())
VALID = {
    "import_statement",
    "import_from_statement",
}


def process_file(fp):
    src = fp.read_bytes()
    tree = parser.parse(src)
    root = tree.root_node
    return [src[node.start_byte : node.end_byte].decode() for node in root.children if node.type in VALID]


def main() -> None:
    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir()
    cwd = Path("/data/data/com.termux/files/usr/lib/python3.12/site-packages")
    p_list = [p for p in cwd.glob("*") if p.name.startswith(("q", "p", "visitor", "dominate"))]
    files = []
    for path in p_list:
        if path.is_file() and path.suffix == ".py":
            files.append(path)
        if path.is_dir():
            files.extend(get_pyfiles(path))
    outfile = Path(f"output/p_importz.py")
    all_imports = []
    results = []
    print(f"{len(files)} files found")
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(process_file, f) for f in files]
        results.extend(future.result() for future in as_completed(futures))
    for imports in results:
        if imports:
            for k in imports:
                if not k.startswith("from .") and k not in all_imports:
                    all_imports.append(k)
    all_imports = sorted(set(all_imports))
    outfile.write_text("\n".join(all_imports), encoding="utf-8")
    print("done.")


if __name__ == "__main__":
    sys.exit(main())
