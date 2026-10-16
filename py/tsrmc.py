import ast
from multiprocessing import get_context
from pathlib import Path

import tree_sitter_python as tspython
from dh import clean_blank_lines, cprint, fsz, gsz
from fastwalk import walk_files
from tree_sitter import Language, Parser, Query, QueryCursor

ts_remover = None


class TSRemover:
    def __init__(self) -> None:
        self.language = Language(tspython.language())
        self.parser = Parser(self.language)
        self.query = Query(
            self.language,
            "\n(comment) @comment\n(block\n  . (expression_statement\n    (string)) @docstring)\n(module\n  . (expression_statement\n    (string)) @docstring)\n",
        )

    def remove_comments(self, source: str):
        source_bytes = source.encode("utf-8")
        tree = self.parser.parse(source_bytes)
        cursor = QueryCursor(self.query)
        matches = cursor.matches(tree.root_node)
        deletions = []
        comment_count = 0
        docstring_count = 0
        for _pattern_index, captures_dict in matches:
            for capture_name, node_list in captures_dict.items():
                for node in node_list:
                    start = node.start_byte
                    end = node.end_byte
                    text = source_bytes[start:end].decode("utf-8")
                    if capture_name == "comment":
                        stripped = text.strip()
                        if stripped.startswith((
                            "# type:",
                            "# black:",
                            "# ruff:",
                            "#!/",
                            "# fmt:",
                            "# pylint:",
                            "# mypy:",
                        )):
                            continue
                        comment_count += 1
                    else:
                        docstring_count += 1
                    if end < len(source_bytes) and source_bytes[end : end + 1] == b"\n":
                        end += 1
                    deletions.append((start, end))
        deletions = sorted(set(deletions), reverse=True)
        new_source = source_bytes
        for start, end in sorted(deletions, reverse=True):
            new_source = new_source[:start] + new_source[end:]
        tree = self.parser.parse(new_source)
        if tree.root_node.has_error:
            print("resulted code is not valid")
            return (source_bytes, 0, 0)
        cleaned = new_source.decode("utf-8")
        cleaned = clean_blank_lines(cleaned)
        return (cleaned, comment_count, docstring_count)


def ts_remover_initializer() -> None:
    global ts_remover
    ts_remover = TSRemover()


def process_file(fp):
    global ts_remover
    file_path = Path(fp)
    try:
        code = Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        cprint(f"[ERROR] {file_path.name} failed to read: {e}", "yellow")
        return ("error", file_path, 0, 0)
    try:
        result, comments, docstrings = ts_remover.remove_comments(code)
    except Exception as e:
        cprint(f"[ERROR] {file_path.name} processing: {e}", "yellow")
        return ("error", file_path, 0, 0)
    if comments != 0 or docstrings != 0:
        try:
            ast.parse(result)
            Path(file_path).write_text(result, encoding="utf-8")
            cprint(f"[OK] {file_path.name}: {comments} comments, {docstrings} docstrings removed", "cyan")
            return ("changed", file_path, comments, docstrings)
        except Exception as e:
            cprint(f"[ERROR] {file_path.name} after strip: {e}", "yellow")
            return ("error", file_path, comments, docstrings)
    else:
        cprint(f"[NO CHANGE] {file_path.name}", "blue")
        return ("nochange", file_path, 0, 0)


if __name__ == "__main__":
    dir_path = Path.cwd()
    files = [Path(p) for p in walk_files(dir_path) if Path(p).is_file() and Path(p).suffix == ".py"]
    before = gsz(dir_path)
    results = []
    nproc = 8
    with get_context("spawn").Pool(processes=nproc, initializer=ts_remover_initializer) as pool:
        results = pool.map(process_file, files)
    after = gsz(dir_path)
    size_diff = before - after
    changed = sum((1 for r in results if r and r[0] == "changed"))
    errors = [r for r in results if r and r[0] == "error"]
    nochg = sum((1 for r in results if r and r[0] == "nochange"))
    print(f"\nProcessed: {len(files)} files: {changed} changed, {nochg} unchanged, {len(errors)} errors")
    if errors:
        print("Files with errors:")
        for _, fn, *_ in errors:
            print(f"  {fn}")
    print(f"dir size reduced: {fsz(size_diff)}")
