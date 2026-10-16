from tree_sitter import Node
import ast
import sys
from multiprocessing import Pool
from pathlib import Path

import tree_sitter_python as tspython
from dh import clean_blank_lines, cprint, get_files
from tree_sitter import Language, Parser


class TSRemover:
    def __init__(self) -> None:
        self.parser = Parser()
        self.parser.language = Language(tspython.language())

    def remove_comments(self, source: str) -> str:
        tree = self.parser.parse(source.encode("utf-8"))
        root = tree.root_node
        to_delete = []

        def walk(node: Node) -> None:
            if node.type == "comment":
                to_delete.append((node.start_byte, node.end_byte))
            if node.type == "expression_statement" and len(node.children) == 1:
                child = node.children[0]
                if child.type == "string":
                    to_delete.append((node.start_byte, node.end_byte))
            for child in node.children:
                walk(child)

        walk(root)
        new_source = source.encode("utf-8")
        for start, end in sorted(to_delete, reverse=True):
            new_source = new_source[:start] + new_source[end:]
        cleaned = new_source.decode("utf-8")
        return clean_blank_lines(cleaned)


def process_file(fp) -> None:
    file_path = Path(fp)
    before = file_path.stat().st_size
    ts_rmc = TSRemover()
    code = file_path.read_text(encoding="utf-8", errors="ignore")
    result = ts_rmc.remove_comments(code)
    if len(result) != len(code):
        try:
            ast.parse(result)
            file_path.write_text(result, encoding="utf-8")
            after = file_path.stat().st_size
            sr = before - after
            cprint(f"[OK] {file_path.name} {fsz(sr)}", "cyan")
            return
        except:
            cprint(f"[ERROR] {file_path.name}", "yellow")
            return
    else:
        cprint(f"[NO CHANGE] {file_path.name}", "blue")
        return


if __name__ == "__main__":
    cwd = Path.cwd()
    before = gsz(cwd)
    args = sys.argv[1:]
    files = [Path(f) for f in args] if args else get_files(cwd, ext=[".py"])
    pool = Pool(8)
    for _ in pool.imap_unordered(process_file, files):
        pass
    pool.close()
    pool.join()
    sres = before - gsz(cwd)
    cprint(f"dir size reduced: {fsz(sres)}", "cyan")
