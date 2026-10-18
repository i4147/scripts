import ast
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_python as tsp
import libcst as cst

_Edit = tuple[int, int, bytes]


@dataclass
class StripFileResult:
    path: Path
    modified: bool
    valid: bool
    error: str | None = None


class TSStripper:
    name = "tree-sitter"

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

        # Robust tree-sitter initialization supporting all versions (0.20 to 0.26+)
        self._language = Language(tsp.language())
        self._parser = Parser()
        try:
            self._parser.language = self._language
        except (AttributeError, ValueError):
            try:
                self._parser.set_language(self._language)
            except (AttributeError, ValueError):
                self._parser = Parser(self._language)

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
        try:
            original = p.read_text(encoding=encoding, newline="")
        except Exception as e:
            return StripFileResult(path=p, modified=False, valid=False, error=f"{type(e).__name__}: {e}")

        try:
            stripped = self._strip_unchecked(original)
        except Exception as e:
            return StripFileResult(path=p, modified=False, valid=False, error=f"{type(e).__name__}: {e}")

        if self.validate and not self._is_valid(stripped):
            err = self._parse_error(stripped) or "invalid Python after stripping"
            return StripFileResult(path=p, modified=False, valid=False, error=err)

        if stripped == original:
            return StripFileResult(path=p, modified=False, valid=True)

        try:
            self._atomic_write(p, stripped, encoding=encoding)
        except Exception as e:
            return StripFileResult(path=p, modified=False, valid=False, error=f"{type(e).__name__}: {e}")

        return StripFileResult(path=p, modified=True, valid=True)

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

    def _strip_unchecked(self, source: str) -> str:
        if not (self.strip_comments or self.strip_docstrings):
            return source

        src = source.encode("utf-8")
        tree = self._parser.parse(src)
        edits: list[_Edit] = []

        if self.strip_comments:
            self._collect_comments(tree.root_node, src, edits)
        if self.strip_docstrings:
            self._collect_docstrings(tree.root_node, src, edits)

        edits = self._merge(edits, src)
        return self._apply(src, edits).decode("utf-8")

    @staticmethod
    def _line_start(src: bytes, pos: int) -> int:
        idx = src.rfind(b"\n", 0, pos)
        return 0 if idx < 0 else idx + 1

    @staticmethod
    def _line_end(src: bytes, pos: int) -> int:
        idx = src.find(b"\n", pos)
        return len(src) if idx < 0 else idx + 1

    def _collect_comments(self, node, src: bytes, edits: list[_Edit]) -> None:
        if node.type == "comment":
            text = src[node.start_byte : node.end_byte]

            if self.preserve_shebangs and node.start_byte == 0 and text.startswith(b"#!"):
                return
            if self.preserve_directives and self._is_directive(text):
                return

            line_start = self._line_start(src, node.start_byte)
            before = src[line_start : node.start_byte]

            if before.strip(b" \t") == b"":
                start = line_start
                end = self._line_end(src, node.end_byte)
            else:
                i = node.start_byte - 1
                while i >= line_start and src[i : i + 1] in (b" ", b"\t"):
                    i -= 1
                start = i + 1
                end = node.end_byte

            edits.append((start, end, b""))
            return

        for child in node.children:
            self._collect_comments(child, src, edits)

    @classmethod
    def _is_directive(cls, comment_bytes: bytes) -> bool:
        text = comment_bytes.decode("utf-8", "replace")
        return bool(cls._DIRECTIVE_RE.match(text))

    def _collect_docstrings(self, node, src: bytes, edits: list[_Edit]) -> None:
        t = node.type

        if t == "module":
            self._strip_container_docstring(node, src, edits, is_module=True)
        elif t in ("function_definition", "class_definition"):
            body = node.child_by_field_name("body")
            if body is not None:
                if body.type == "block":
                    self._strip_container_docstring(body, src, edits, is_module=False)
                elif body.type == "expression_statement" and self._is_string_expr(body):
                    edits.append((body.start_byte, body.end_byte, b"pass"))

        for child in node.children:
            self._collect_docstrings(child, src, edits)

    @staticmethod
    def _is_string_expr(stmt) -> bool:
        named = [c for c in stmt.children if c.is_named]
        return len(named) == 1 and named[0].type in ("string", "concatenated_string")

    @staticmethod
    def _first_statement(container):
        for child in container.named_children:
            if child.type == "comment":
                continue
            return child
        return None

    def _strip_container_docstring(
        self,
        container,
        src: bytes,
        edits: list[_Edit],
        *,
        is_module: bool,
    ) -> None:
        if is_module and self.preserve_module_docstring:
            return

        first = self._first_statement(container)
        if first is None or first.type != "expression_statement":
            return
        if not self._is_string_expr(first):
            return

        real_stmts = [c for c in container.named_children if c.type != "comment"]
        only_stmt = len(real_stmts) == 1

        if only_stmt and not is_module:
            edits.append((first.start_byte, first.end_byte, b"pass"))
        else:
            start = self._line_start(src, first.start_byte)
            end = self._line_end(src, first.end_byte)
            edits.append((start, end, b""))

    @staticmethod
    def _merge(edits: list[_Edit], src: bytes) -> list[_Edit]:
        if not edits:
            return []
        edits.sort(key=lambda e: (e[0], e[1]))
        merged: list[_Edit] = [edits[0]]
        for start, end, repl in edits[1:]:
            pstart, pend, prepl = merged[-1]
            if start <= pend:
                new_end = max(end, pend)
                new_repl = prepl if prepl else repl
                merged[-1] = (pstart, new_end, new_repl)
            else:
                merged.append((start, end, repl))
        return merged

    @staticmethod
    def _apply(src: bytes, edits: list[_Edit]) -> bytes:
        if not edits:
            return src
        out = bytearray()
        cursor = 0
        for start, end, repl in edits:
            out.extend(src[cursor:start])
            out.extend(repl)
            cursor = end
        out.extend(src[cursor:])
        return bytes(out)

    @staticmethod
    def _atomic_write(path: Path, text: str, *, encoding: str = "utf-8") -> None:
        directory = path.parent
        directory.mkdir(parents=True, exist_ok=True)
        # Use directory=path.parent to prevent cross-device link errors
        fd, tmp_name = tempfile.mkstemp(
            dir=directory,
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
                if path.exists():
                    st = path.stat()
                    os.chmod(tmp_path, st.st_mode)
            except OSError:
                pass

            # True atomic replacement (atomic on POSIX and Windows)
            tmp_path.replace(path)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise


# =====================================================================
# LibCST Stripper
# =====================================================================


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
        try:
            with open(p, "r", encoding=encoding, newline="") as f:
                original = f.read()
        except Exception as e:
            return StripFileResult(path=p, modified=False, valid=False, error=f"{type(e).__name__}: {e}")

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

        try:
            self._atomic_write(p, stripped, encoding=encoding)
        except Exception as e:
            return StripFileResult(path=p, modified=False, valid=False, error=f"{type(e).__name__}: {e}")

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
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=directory,
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
                if path.exists():
                    st = path.stat()
                    os.chmod(tmp_path, st.st_mode)
            except OSError:
                pass

            tmp_path.replace(path)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
