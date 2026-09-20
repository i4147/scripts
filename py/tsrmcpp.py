from tree_sitter import Parser
from tree_sitter import Node
from pathlib import Path

import tree_sitter_cpp as tscpp
from dh import clean_blank_lines, cprint, run_command
from tree_sitter import Language, Parser


class TSCppRemover:
    def __init__(self) -> None:
        self.parser = Parser()
        self.language = Language(tscpp.language())
        self.parser.language = self.language

    def remove_comments(self, source: str) -> tuple[str, int]:
        source_bytes = source.encode("utf-8")
        tree = self.parser.parse(source_bytes)
        root = tree.root_node
        to_delete = []
        removed = 0
        for node in root.children:
            self._collect_comments(node, to_delete, source_bytes)
        new_source = source_bytes
        for start, end in sorted(to_delete, reverse=True):
            new_source = new_source[:start] + new_source[end:]
            removed += 1
        cleaned = new_source.decode("utf-8")
        cleaned = clean_blank_lines(cleaned)
        return (cleaned, removed)

    def _collect_comments(self, node: Node, to_delete, source_bytes: bytes) -> None:
        if node.type == "comment":
            text = source_bytes[node.start_byte : node.end_byte].decode("utf-8").strip()
            if text.startswith("#"):
                return
            to_delete.append((node.start_byte, node.end_byte))
        for child in node.children:
            self._collect_comments(child, to_delete, source_bytes)


def validate_with_treesitter(parser: Parser, code: str) -> bool:
    tree = parser.parse(code.encode("utf-8"))
    return not tree.root_node.has_error


def validate_with_clang(file_path: Path) -> tuple[bool, str]:
    cmd = f"clang++ -std=c++20 -fsyntax-only {file_path!s}"
    ret, txt, err = run_command(cmd)
    if ret != 0:
        return (False, err)
    if ret == 0:
        return (True, txt)
    return None


def process_file(fp: Path) -> None:
    file_path = Path(fp)
    before = file_path.stat().st_size
    remover = TSCppRemover()
    code = file_path.read_text(encoding="utf-8", errors="ignore")
    result, removed = remover.remove_comments(code)
    if removed == 0:
        cprint(f"[NO CHANGE] {file_path.name}", "blue")
        return
    if not validate_with_treesitter(remover.parser, result):
        cprint(f"[TS ERROR] {file_path.name} - changes discarded", "red")
        return
    file_path.write_text(result, encoding="utf-8")
    ok, _err = validate_with_clang(file_path)
    if not ok:
        cprint(f"[CLANG ERROR] {file_path.name} - reverting", "red")
        file_path.write_text(code, encoding="utf-8")
        return
    after = file_path.stat().st_size
    reduced = before - after
    cprint(f"[OK] {file_path.name} - removed {removed} comments, reduced {reduced} bytes", "cyan")


if __name__ == "__main__":
    exts = {".cpp", ".cc", ".cxx", ".hpp", ".h", ".hh", ".hxx", ".c"}
    for path in Path().rglob("*"):
        if path.is_file() and path.suffix in exts:
            process_file(path)
