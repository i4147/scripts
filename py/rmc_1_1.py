from tree_sitter import Node
from ast import parse as ast_parse
from operator import itemgetter
from pathlib import Path

import tree_sitter_python as tsp
from dh import clean_blank_lines, cprint, fsz, gsz, have_doc
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tsp.language())
parser = Parser(PY_LANGUAGE)


def strip_code(code: str):
    try:
        tree = parser.parse(bytes(code, "utf8"))
        root_node = tree.root_node
        to_delete = []
        to_replace_with_pass = []

        def traverse(node: Node) -> None:

            def should_preserve_comment(content) -> bool:
                content = content.strip()
                PRESERVED: set = {"#!", "# type", "# fmt"}
                return any((pat in content for pat in PRESERVED))

            if node.type == "comment":
                comment_text = code[node.start_byte : node.end_byte]
                if not should_preserve_comment(comment_text):
                    to_delete.append((node.start_byte, node.end_byte))
            elif node.type == "expression_statement":
                child = node.named_children[0] if node.named_children else None
                if child and child.type == "string":
                    parent = node.parent
                    if parent and parent.type == "block":
                        if parent.named_child_count == 1:
                            to_replace_with_pass.append((node.start_byte, node.end_byte))
                        else:
                            to_delete.append((node.start_byte, node.end_byte))
            for child in node.children:
                traverse(child)

        traverse(root_node)
        modifications = [(s, e, "") for s, e in to_delete]
        modifications += [(s, e, "pass") for s, e in to_replace_with_pass]
        modifications.sort(key=itemgetter(0), reverse=True)
        working_code = code
        for start, end, replacement in modifications:
            working_code = working_code[:start] + replacement + working_code[end:]
        return working_code
    except:
        print(f"error")
        return code


def process_file(path: Path) -> bool:
    before = gsz(path)
    original = path.read_text(encoding="utf-8")
    if have_doc(original):
        finalcode = strip_code(original)
        wcode = clean_blank_lines(finalcode)
        try:
            _ = ast_parse(wcode)
            print(f"{path.name}", end=" ")
            if len(wcode) == len(original):
                cprint("(no change)", "magenta")
                return True
            path.write_text(wcode, encoding="utf-8")
            after = gsz(path)
            dsz = before - after
            if dsz:
                cprint(f"{fsz(before - gsz(path))}", "blue")
            else:
                cprint("(no change)", "grey")
            return True
        except:
            cprint(f"{path.name} ast parse error", "yellow")
            return False
    return False


if __name__ == "__main__":
    from sys import argv as sys_argv

    from dh import get_pyfiles, mpf3

    cwd = Path.cwd()
    args = sys_argv[1:]
    files = [Path(f) for f in args] if args else get_pyfiles(cwd)
    print(f"{len(files)} files found.")
    _ = mpf3(process_file, files)
