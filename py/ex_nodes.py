import argparse
from collections import defaultdict
from pathlib import Path
import tree_sitter_python as tsp
from tree_sitter import Language, Parser, Tree

KINDS = {
    "class": {"class_definition"},
    "func": {"function_definition"},
    "docstrings": {"function_docstrings", "class_docstrings"},
    "comments": {"comment", "expression_statements"},
}
KINDS["all"] = set().union(*KINDS.values())
SKIP_PARTS = {"site-packages", "__pycache__", ".git"}


def build_parser():
    parser = Parser()
    parser.language = Language(tsp.language())
    return parser


def extract_file(src, tree, valid):
    root = tree.root_node
    return [src[node.start_byte : node.end_byte].decode() for node in root.children if node.type in valid]


def iter_py_files(roots, out_dir):
    found = []
    resolved_out = out_dir.resolve()
    for root in roots:
        candidates = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for py in candidates:
            if any(part.startswith(".") for part in py.parts):
                continue
            if SKIP_PARTS.intersection(py.parts):
                continue
            if py.resolve().parent == resolved_out or resolved_out in py.resolve().parents:
                continue
            found.append(py)
    return found


def out_subdir(folder):
    try:
        return folder.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return Path(folder.name)


def main():
    ap = argparse.ArgumentParser(
        description=(
            "Extract top-level Python nodes (functions, classes, docstrings or "
            "comments) with tree-sitter into output/<folder>/imports.py."
        )
    )
    ap.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="files or directories to scan (default: current directory)",
    )
    ap.add_argument(
        "--kind",
        default="func",
        choices=sorted(KINDS),
        help="which tree-sitter node types to keep (default: func)",
    )
    ap.add_argument(
        "--out",
        default=Path("output"),
        type=Path,
        help="output directory (default: ./output)",
    )
    args = ap.parse_args()
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    valid = KINDS[args.kind]
    parser = build_parser()
    folder_nodes = defaultdict(list)
    for py in iter_py_files(args.paths or [Path()], out_dir):
        try:
            src = py.read_bytes()
        except OSError:
            continue
        nodes = extract_file(src, parser.parse(src), valid)
        if nodes:
            folder_nodes[py.parent].append("\n".join(nodes))
    for folder, chunks in folder_nodes.items():
        out_file = out_dir / out_subdir(folder) / "imports.py"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text("\n\n".join(chunks), encoding="utf-8")
    print(f"\n✨ Done! kind={args.kind} nodes={sorted(valid)} processed {len(folder_nodes)} folder(s) -> {out_dir}/")


if __name__ == "__main__":
    raise SystemExit(main())
