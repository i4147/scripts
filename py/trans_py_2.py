import ast
import re
import shutil
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final, cast
from deep_translator import GoogleTranslator
from dh import get_pyfiles
from loguru import logger

CHUNK_SIZE = 5000
MAX_WORKERS = 8
SKIP_DIRS = frozenset({"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"})
NON_ASCII_PATTERN = re.compile(r"[^\x00-\x7F]")


def translate_text(text):
    if not text.strip() or not NON_ASCII_PATTERN.search(text):
        return text
    try:
        translator = GoogleTranslator(source="auto", target="en")
        translated = translator.translate(text.strip())
        return translated if translated else text
    except Exception as exc:
        logger.debug(f"Translation error: {exc} for text: {text[:30]}")
        return text


class DocstringCommentTransformer(ast.NodeTransformer):
    def __init__(self):
        self.modified = False

    def _translate_node_docstring(self, node):
        docstring = ast.get_docstring(node)
        if docstring and NON_ASCII_PATTERN.search(docstring):
            translated = translate_text(docstring)
            if translated != docstring:
                self.modified = True
                body = getattr(node, "body", [])
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    body[0].value.value = translated

    def visit_FunctionDef(self, node):
        self._translate_node_docstring(node)
        return cast(ast.FunctionDef, self.generic_visit(node))

    def visit_ClassDef(self, node):
        self._translate_node_docstring(node)
        return cast(ast.ClassDef, self.generic_visit(node))

    def visit_Module(self, node):
        self._translate_node_docstring(node)
        return cast(ast.Module, self.generic_visit(node))


def translate_comments(content):
    lines = content.splitlines(keepends=True)
    new_lines = []
    modified = False
    for line in lines:
        if "#" in line:
            parts = line.split("#", 1)
            comment = parts[1]
            if NON_ASCII_PATTERN.search(comment):
                translated = translate_text(comment)
                if translated != comment:
                    new_lines.append(f"{parts[0]}# {translated}\n")
                    modified = True
                    continue
        new_lines.append(line)
    return "".join(new_lines), modified


def process_file(filepath):
    try:
        backup_path = filepath.with_suffix(filepath.suffix + ".bak")
        shutil.copyfile(filepath, backup_path)
        content = filepath.read_text(encoding="utf-8")
        content_after_comments, comments_modified = translate_comments(content)
        try:
            tree = ast.parse(content_after_comments)
            transformer = DocstringCommentTransformer()
            new_tree = transformer.visit(tree)
            if transformer.modified or comments_modified:
                new_content = ast.unparse(new_tree)
                filepath.write_text(new_content, encoding="utf-8")
                return True
        except SyntaxError:
            if comments_modified:
                filepath.write_text(content_after_comments, encoding="utf-8")
                return True
    except Exception as exc:
        logger.error(f"Failed to process {filepath}: {exc}")
    return False


def main():
    cwd = Path.cwd()
    py_files = get_pyfiles(cwd)
    if not py_files:
        print("No Python files found.")
        return
    print(f"Processing {len(py_files)} files...")
    modified_count = 0
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(process_file, (f,)) for f in py_files]
        for file_path, async_res in zip(py_files, async_results):
            if async_res.get():
                modified_count += 1
                print(f"✓ Updated: {file_path.name}")
    print(f"Done. Modified {modified_count} files.")


if __name__ == "__main__":
    raise SystemExit(main())
