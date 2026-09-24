from __future__ import annotations

import ast
import logging
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Final

from deep_translator import GoogleTranslator
from dh import get_pyfiles

CHUNK_SIZE = 1024 * 1024
SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
CHUNK_SIZE: Final[int] = 5000
NON_ASCII_PATTERN: Final[re.Pattern] = re.compile(r"[^\x00-\x7F]")
MAX_WORKERS: Final[int] = 8
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def translate_text(text: str) -> str:
    if not text.strip() or not NON_ASCII_PATTERN.search(text):
        return text
    try:
        translator = GoogleTranslator(source="auto", target="en")
        translated = translator.translate(text.strip())
        return translated if translated else text
    except Exception as e:
        logger.debug("Translation error: %s for text: %s", e, text[:30])
        return text


class DocstringCommentTransformer(ast.NodeTransformer):
    def __init__(self):
        self.modified = False

    def _translate_node_docstring(self, node: Any) -> None:
        docstring = ast.get_docstring(node)
        if docstring and NON_ASCII_PATTERN.search(docstring):
            translated = translate_text(docstring)
            if translated != docstring:
                self.modified = True
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                ):
                    node.body[0].value.value = translated

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        self._translate_node_docstring(node)
        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        self._translate_node_docstring(node)
        return self.generic_visit(node)

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self._translate_node_docstring(node)
        return self.generic_visit(node)


def translate_comments(content: str) -> tuple[str, bool]:
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
    return ("".join(new_lines), modified)


def process_file(path: Path) -> bool:
    try:
        backup_path = path.with_suffix(path.suffix + ".bak")
        shutil.copyfile(path, backup_path)
        content = path.read_text(encoding="utf-8")
        content_after_comments, comments_modified = translate_comments(content)
        try:
            tree = ast.parse(content_after_comments)
            transformer = DocstringCommentTransformer()
            new_tree = transformer.visit(tree)
            if transformer.modified or comments_modified:
                new_content = ast.unparse(new_tree)
                path.write_text(new_content, encoding="utf-8")
                return True
        except SyntaxError:
            if comments_modified:
                path.write_text(content_after_comments, encoding="utf-8")
                return True
    except Exception as e:
        logger.error("Failed to process %s: %s", path, e)
    return False


def main() -> None:
    cwd = Path.cwd()
    py_files = get_pyfiles(cwd)
    if not py_files:
        logger.info("No Python files found.")
        return
    logger.info("Processing %d files...", len(py_files))
    modified_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_file = {executor.submit(process_file, f): f for f in py_files}
        for future in as_completed(future_to_file):
            if future.result():
                modified_count += 1
                logger.info("✓ Updated: %s", future_to_file[future].name)
    logger.info("Done. Modified %d files.", modified_count)


if __name__ == "__main__":
    raise SystemExit(main())
