from __future__ import annotations

import ast
import logging
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Final

from deep_translator import GoogleTranslator

SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
JAPANESE_PATTERN: Final[re.Pattern] = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def translate_text(text: str) -> str:
    if not text or not text.strip() or (not JAPANESE_PATTERN.search(text)):
        return text
    try:
        translator = GoogleTranslator(source="ja", target="en")
        translated = translator.translate(text)
        return translated if translated else text
    except Exception as e:
        logger.error("Translation error: %s for text snippet: %s", e, text[:50])
        return text


class CommentDocstringTransformer(ast.NodeTransformer):
    def __init__(self):
        self.modified = False

    def _process_docstring(self, node: Any) -> None:
        docstring = ast.get_docstring(node)
        if docstring and JAPANESE_PATTERN.search(docstring):
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
        self._process_docstring(node)
        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        self._process_docstring(node)
        return self.generic_visit(node)

    def visit_Module(self, node: ast.Module) -> ast.Module:
        self._process_docstring(node)
        return self.generic_visit(node)


def translate_comments_in_content(content: str) -> tuple[str, bool]:
    lines = content.splitlines(keepends=True)
    modified = False
    new_lines = []
    for line in lines:
        if "#" in line:
            parts = line.split("#", 1)
            comment = parts[1]
            if JAPANESE_PATTERN.search(comment):
                translated_comment = translate_text(comment)
                if translated_comment != comment:
                    new_lines.append(f"{parts[0]}#{translated_comment}")
                    modified = True
                    continue
        new_lines.append(line)
    return ("".join(new_lines), modified)


def translate_file(file_path: Path) -> bool:
    try:
        content = file_path.read_text(encoding="utf-8")
        content_after_comments, comments_modified = translate_comments_in_content(content)
        try:
            tree = ast.parse(content_after_comments)
            transformer = CommentDocstringTransformer()
            new_tree = transformer.visit(tree)
            docstrings_modified = transformer.modified
            if comments_modified or docstrings_modified:
                new_content = ast.unparse(new_tree)
                if JAPANESE_PATTERN.search(new_content):
                    new_content = JAPANESE_PATTERN.sub(lambda m: translate_text(m.group(0)), new_content)
                file_path.write_text(new_content, encoding="utf-8")
                return True
        except SyntaxError as e:
            logger.error("Syntax error in %s: %s. Skipping AST translation.", file_path, e)
            if comments_modified:
                file_path.write_text(content_after_comments, encoding="utf-8")
                return True
            return False
    except Exception as e:
        logger.error("Error processing %s: %s", file_path, e)
        return False
    return False


def main() -> None:
    start_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    start_path = Path(start_dir).resolve()
    if not start_path.exists():
        logger.error("Error: Path '%s' does not exist", start_path)
        sys.exit(1)
    logger.info("Scanning for Python files in: %s", start_path)
    py_files = [f for f in start_path.rglob("*.py") if not any(part in SKIP_DIRS for part in f.parts)]
    if not py_files:
        logger.info("No Python files found.")
        return
    logger.info("Found %d Python files. Starting translation...", len(py_files))
    modified_count = 0
    with ProcessPoolExecutor() as executor:
        future_to_file = {executor.submit(translate_file, f): f for f in py_files}
        for future in as_completed(future_to_file):
            if future.result():
                modified_count += 1
                logger.info("✓ Updated: %s", future_to_file[future])
    logger.info("\n" + "=" * 40)
    logger.info("Completed! Modified %d out of %d files", modified_count, len(py_files))


if __name__ == "__main__":
    raise SystemExit(main())
