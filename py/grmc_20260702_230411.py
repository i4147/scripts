import ast
import io
import sys
import tokenize
from pathlib import Path
from tokenize import untokenize
from dh import get_files, mpf3


def process_file(path):
    path = Path(path)
    source = path.read_text(encoding="utf-8")
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        tokens = list(tokens)
    except tokenize.TokenError:
        tokens = tokenize.generate_tokens(io.BytesIO(source.encode("utf-8")).readline)
        tokens = list(tokens)
    tokens = [tok for tok in tokens if tok.type != tokenize.COMMENT]
    source_no_comments = untokenize(tokens)
    try:
        tree = ast.parse(source_no_comments)
    except SyntaxError:
        return source_no_comments

    class DocstringRemover(ast.NodeTransformer):
        def visit_Module(self, node):
            if (
                len(node.body) >= 1
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:]
            return self.generic_visit(node)

        def visit_FunctionDef(self, node):
            if (
                len(node.body) >= 1
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:]
            return self.generic_visit(node)

        def visit_ClassDef(self, node):
            if (
                len(node.body) >= 1
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:]
            return self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            if (
                len(node.body) >= 1
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:]
            return self.generic_visit(node)

    tree = DocstringRemover().visit(tree)
    cleaned_source = ast.unparse(tree)
    path.write_text(cleaned_source, encoding="utf-8")
    return


def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(cwd)
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)
    mpf3(process_file, files)


if __name__ == "__main__":
    sys.exit(main())
