from tree_sitter import Node
import sys
from pathlib import Path

import tree_sitter_rust
from dh import clean_blank_lines, cprint, fsz, gsz
from tree_sitter import Language, Parser

EXCLUDE_PREFIXES = (b"#!/",)
parser = Parser()
parser.language = Language(tree_sitter_rust.language())


def process_file(path: Path) -> None:
    print(f"processing {path.name}")
    try:
        source = path.read_bytes()
        tree = parser.parse(source)
        deletions = []

        def walk(node: Node) -> None:
            if node.type == "comment":
                text = source[node.start_byte : node.end_byte]
                if text.lstrip().startswith(EXCLUDE_PREFIXES):
                    return
                deletions.append((node.start_byte, node.end_byte))
            for child in node.children:
                walk(child)

        walk(tree.root_node)
        if not deletions:
            return
        cleaned = bytearray(source)
        for start, end in sorted(deletions, reverse=True):
            del cleaned[start:end]
        cleaned_text = cleaned.decode("utf-8")
        cleaned_text = clean_blank_lines(cleaned_text)
        cleaned = cleaned_text.encode("utf-8")
        parser.parse(cleaned)
        path.write_bytes(cleaned)
        print(f"[OK] {path.name}")
    except Exception as e:
        cprint(f"[FAIL] {path.name} -> {e}", "cyan")


def collect_rs_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix == ".rs":
        return [root]
    return [p for p in root.rglob("*.rs") if p.is_file()]


def main() -> None:
    root = Path().cwd().resolve()
    files = collect_rs_files(root)
    if not files:
        sys.exit("No Rust files found")
    before = gsz(root)
    for f in files:
        process_file(f)
    after = gsz(root)
    difsize = before - after
    cprint(f"{fsz(difsize)}", "cyan")


if __name__ == "__main__":
    main()
