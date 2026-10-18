import ast
import dataclasses
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
import shutil

import libcst as cst


@dataclass
class StripFileResult:
    path: Path
    modified: bool
    valid: bool
    error: str | None = None


class _CommentRemover(cst.CSTTransformer):
    def __init__(
        self,
        preserve_shebangs: bool,
        preserve_directives: bool,
        directive_re: re.Pattern[str],
    ) -> None:
        super().__init__()
        self.preserve_shebangs = preserve_shebangs
        self.preserve_directives = preserve_directives
        self.directive_re = directive_re
        self._shebang_comment: cst.Comment | None = None
        self._emptied_ids: set[int] = set()

    def visit_Module(self, node: cst.Module) -> bool:
        if self.preserve_shebangs and node.header:
            first = node.header[0]
            if isinstance(first, cst.EmptyLine) and first.comment is not None and first.comment.value.startswith("#!"):
                self._shebang_comment = first.comment
        return True

    def _keep(self, comment: cst.Comment) -> bool:
        if comment is self._shebang_comment:
            return True
        if self.preserve_directives and self.directive_re.match(comment.value):
            return True
        return False

    def leave_EmptyLine(self, original: cst.EmptyLine, updated: cst.EmptyLine) -> cst.EmptyLine:
        if original.comment is None:
            return updated
        if self._keep(original.comment):
            return updated
        emptied = updated.with_changes(comment=None)
        self._emptied_ids.add(id(emptied))
        return emptied

    def leave_TrailingWhitespace(
        self,
        original: cst.TrailingWhitespace,
        updated: cst.TrailingWhitespace,
    ) -> cst.TrailingWhitespace:
        if original.comment is None:
            return updated
        if self._keep(original.comment):
            return updated
        return updated.with_changes(
            comment=None,
            whitespace=cst.SimpleWhitespace(""),
        )

    def on_leave(self, original_node, updated_node):
        if not self._emptied_ids:
            return updated_node
        changes: dict[str, tuple] = {}
        for field in dataclasses.fields(updated_node):
            value = getattr(updated_node, field.name)
            if isinstance(value, (list, tuple)) and value:
                filtered = tuple(x for x in value if id(x) not in self._emptied_ids)
                if len(filtered) != len(value):
                    changes[field.name] = filtered
        if changes:
            return updated_node.with_changes(**changes)
        return updated_node


class _DocstringRemover(cst.CSTTransformer):
    def __init__(self, preserve_module_docstring: bool) -> None:
        super().__init__()
        self.preserve_module_docstring = preserve_module_docstring

    @staticmethod
    def _is_docstring_stmt(stmt: cst.CSTNode) -> bool:
        if not isinstance(stmt, cst.SimpleStatementLine):
            return False
        if len(stmt.body) != 1:
            return False
        expr = stmt.body[0]
        return isinstance(expr, cst.Expr) and isinstance(expr.value, (cst.SimpleString, cst.ConcatenatedString))

    @staticmethod
    def _is_docstring_expr(stmt: cst.BaseSmallStatement) -> bool:
        return isinstance(stmt, cst.Expr) and isinstance(stmt.value, (cst.SimpleString, cst.ConcatenatedString))

    @staticmethod
    def _pass_line() -> cst.SimpleStatementLine:
        return cst.SimpleStatementLine(body=[cst.Pass()])

    def leave_Module(self, original: cst.Module, updated: cst.Module) -> cst.Module:
        if self.preserve_module_docstring:
            return updated
        body = updated.body
        if body and self._is_docstring_stmt(body[0]):
            return updated.with_changes(body=body[1:])
        return updated

    def leave_IndentedBlock(self, original: cst.IndentedBlock, updated: cst.IndentedBlock) -> cst.IndentedBlock:
        body = updated.body
        if body and self._is_docstring_stmt(body[0]):
            new_body = list(body[1:])
            if not new_body:
                new_body = [self._pass_line()]
            return updated.with_changes(body=new_body)
        return updated

    def leave_SimpleStatementSuite(
        self,
        original: cst.SimpleStatementSuite,
        updated: cst.SimpleStatementSuite,
    ) -> cst.SimpleStatementSuite:
        body = updated.body
        if body and self._is_docstring_expr(body[0]):
            new_body = list(body[1:])
            if not new_body:
                new_body = [cst.Pass()]
            return updated.with_changes(body=new_body)
        return updated


class CSTStripper:
    name = "libcst"

    _DIRECTIVE_RE = re.compile(
        r"^#\s*(type|fmt|mypy|pylint|ruff|pyright|noqa)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        strip_comments: bool = True,
        strip_docstrings: bool = True,
        preserve_shebangs: bool = False,
        preserve_module_docstring: bool = False,
        preserve_directives: bool = True,
        validate: bool = True,
    ) -> None:
        self.strip_comments = strip_comments
        self.strip_docstrings = strip_docstrings
        self.preserve_shebangs = preserve_shebangs
        self.preserve_module_docstring = preserve_module_docstring
        self.preserve_directives = preserve_directives
        self.validate = validate

    def strip(self, source: str) -> str:
        try:
            result = self._strip_unchecked(source)
        except Exception:
            return source
        if self.validate and not self._is_valid(result):
            return source
        return result

    def strip_file(
        self,
        path: str | os.PathLike[str],
        *,
        encoding: str = "utf-8",
    ) -> StripFileResult:
        p = Path(path)
        with open(p, "r", encoding=encoding, newline="") as f:
            original = f.read()

        try:
            stripped = self._strip_unchecked(original)
        except Exception as e:
            return StripFileResult(
                path=p,
                modified=False,
                valid=False,
                error=f"{type(e).__name__}: {e}",
            )

        if self.validate and not self._is_valid(stripped):
            err = self._parse_error(stripped) or "invalid Python after stripping"
            return StripFileResult(path=p, modified=False, valid=False, error=err)

        if stripped == original:
            return StripFileResult(path=p, modified=False, valid=True)

        self._atomic_write(p, stripped, encoding=encoding)
        return StripFileResult(path=p, modified=True, valid=True)

    def _strip_unchecked(self, source: str) -> str:
        if not (self.strip_comments or self.strip_docstrings):
            return source

        module = cst.parse_module(source)

        if self.strip_docstrings:
            module = module.visit(_DocstringRemover(self.preserve_module_docstring))
        if self.strip_comments:
            module = module.visit(
                _CommentRemover(
                    self.preserve_shebangs,
                    self.preserve_directives,
                    self._DIRECTIVE_RE,
                )
            )
        return module.code

    @staticmethod
    def _is_valid(source: str) -> bool:
        try:
            ast.parse(source)
        except SyntaxError:
            return False
        return True

    @staticmethod
    def _parse_error(source: str) -> str | None:
        try:
            ast.parse(source)
        except SyntaxError as e:
            return f"{type(e).__name__}: {e}"
        return None

    @staticmethod
    def _atomic_write(path: Path, text: str, *, encoding: str = "utf-8") -> None:
        directory = path.parent
        tmp_dir = os.environ.get("TMPDIR")
        fd, tmp_name = tempfile.mkstemp(
            dir=tmp_dir,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())

            try:
                st = path.stat()
                os.chmod(tmp_path, st.st_mode)
            except OSError:
                pass

            shutil.copy2(tmp_path, path)
            tmp_path.unlink()
        except BaseException:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise
