import ast
import sys
from multiprocessing import Pool
from pathlib import Path
import tree_sitter_python as tspython
from dh import collect_py_files, file_size, folder_size, format_size
from termcolor import cprint
from tree_sitter import Language, Parser, Query, QueryCursor

QUERY_STRING = "\n(comment) @comment\n(module\n  (expression_statement\n    (string) @module_docstring))\n(function_definition\n  body: (block\n    . (expression_statement\n      (string) @function_docstring)))\n(class_definition\n  body: (block\n    . (expression_statement\n      (string) @class_docstring)))\n"


class TSRemover:
    def __init__(self) -> None:
        self.language = Language(tspython.language())
        self.parser = Parser(self.language)
        self.query = Query(self.language, QUERY_STRING)

    def remove_comments(self, source: str) -> tuple[str, int, int]:
        source_bytes = source.encode("utf-8")
        tree = self.parser.parse(source_bytes)
        query_cursor = QueryCursor(self.query)
        matches = query_cursor.matches(tree.root_node)
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
                            "# TODO",
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
        for start, end in deletions:
            new_source = new_source[:start] + new_source[end:]
        cleaned = new_source.decode("utf-8")
        cleaned = self._cleanup_blank_lines(cleaned)
        return (cleaned, comment_count, docstring_count)

    @staticmethod
    def _cleanup_blank_lines(text: str) -> str:
        lines = text.splitlines()
        cleaned = []
        blank_streak = 0
        for line in lines:
            if line.strip() == "":
                blank_streak += 1
                if blank_streak <= 2:
                    cleaned.append("")
            else:
                blank_streak = 0
                cleaned.append(line.rstrip())
        return "\n".join(cleaned) + "\n"


def process_file(fp: Path) -> None:
    file_path = Path(fp)
    ts_rmc = TSRemover()
    before = file_size(file_path)
    code = file_path.read_text(encoding="utf-8", errors="ignore")
    result, comments, docstrings = ts_rmc.remove_comments(code)
    if comments != 0 or docstrings != 0:
        try:
            ast.parse(result)
            file_path.write_text(result, encoding="utf-8")
            after = file_size(file_path)
            cprint(f"[OK] {file_path.name}:[{comments}/{docstrings}] [{format_size(before - after)}]", "cyan")
            return
        except:
            cprint(f"[ERROR] {file_path.name}", "yellow")
            return
    else:
        cprint(f"[NO CHANGE] {file_path.name}", "blue")
        return


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        files = [Path(p) for p in args]
        if len(files) == 1:
            process_file(files[0])
            sys.exit(0)
    else:
        dir = Path().cwd()
        files = collect_py_files(dir)
        init_size = folder_size(dir)
        pool = Pool(8)
        for _ in pool.imap_unordered(process_file, files):
            pass
        pool.close()
        pool.join()
        end_size = folder_size(dir)
        print(f"dir size reduced: {format_size(init_size - end_size)}")
