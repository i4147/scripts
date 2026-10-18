import ast as py_ast
import io
import re
import tokenize
from pathlib import Path
from typing import List, Tuple, Union


class BaseStripper:
    """Base class providing shared regex patterns, blank-line handling, and in-place file stripping."""

    DIRECTIVE_RE = re.compile(
        r"^#\s*(?:type|fmt|mypy|pylint|ruff|pyright|basedpyright|noqa|nosec|bandit|isort|yapf|autopep8|flake8|black|pyre|pytype|pragma|coverage|doctest|pytest|cython|distutils|numba|region|endregion|uv)\b"
        r"|^#\s*(?:%%|</?editor-fold\b)",
        re.I,
    )
    COOKIE_RE = re.compile(rb"coding[:=]\s*[-\w.]+")

    def __init__(
        self,
        strip_comments: bool = False,
        strip_docstrings: bool = False,
        remove_blank_lines: bool = False,
        strip_all: bool = False,
        preserve: bool = True,
    ):
        self.strip_comments = strip_comments or strip_all
        self.strip_docstrings = strip_docstrings or strip_all
        self.strip_all = strip_all
        self.remove_blank_lines = remove_blank_lines
        self.preserve = preserve

    @staticmethod
    def _line_start(source_bytes: bytes, index: int) -> int:
        return source_bytes.rfind(b"\n", 0, index) + 1

    @staticmethod
    def _line_end(source_bytes: bytes, index: int) -> int:
        found = source_bytes.find(b"\n", index)
        return len(source_bytes) if found < 0 else found + 1

    def _keep_comment(self, comment_text: str, line_index: int) -> bool:
        if self.strip_all or not self.preserve:
            return False
        return bool(
            (line_index == 0 and comment_text.startswith("#!"))
            or (line_index < 2 and self.COOKIE_RE.search(comment_text.encode("utf-8")))
            or self.DIRECTIVE_RE.match(comment_text)
        )

    @staticmethod
    def _apply_edits(source_bytes: bytes, edits: List[Tuple[int, int, bytes]]) -> bytes:
        output = bytearray()
        cursor = 0
        for start, end, replacement in sorted(edits):
            if start < cursor:
                raise ValueError("Overlapping source edits")
            output.extend(source_bytes[cursor:start])
            output.extend(replacement)
            cursor = end
        output.extend(source_bytes[cursor:])
        return bytes(output)

    @staticmethod
    def _remove_blank_lines_ast(code: str) -> str:
        active_lines = set()
        for token in tokenize.generate_tokens(io.StringIO(code).readline):
            if token.start[0] != token.end[0]:
                active_lines.update(range(token.start[0], token.end[0] + 1))

        lines = io.StringIO(code).readlines()
        for idx, line in enumerate(lines, 1):
            if line.rstrip("\n").endswith("\\"):
                active_lines.add(idx + 1)
            if idx <= 2 and BaseStripper.COOKIE_RE.search(line.encode("utf-8")):
                active_lines.update(range(1, idx + 1))

        cleaned_code = "".join(
            (line for idx, line in enumerate(lines, 1) if idx in active_lines or line.strip(" \t\f\v"))
        )

        original_ast = py_ast.dump(py_ast.parse(code), include_attributes=False)
        cleaned_ast = py_ast.dump(py_ast.parse(cleaned_code), include_attributes=False)
        if original_ast != cleaned_ast:
            raise ValueError("Blank-line removal would change the AST; not written")
        return cleaned_code

    def strip_file(self, file_path: Union[str, Path]) -> int:
        """Reads a file, strips it in place, validates syntax, writes back, and returns bytes reduced."""
        path = Path(file_path)
        original_bytes = path.read_bytes()
        code = original_bytes.decode("utf-8", errors="replace")

        cleaned_code = self.strip(code)

        # Validate resulting syntax
        py_ast.parse(cleaned_code)

        new_bytes = cleaned_code.encode("utf-8")
        path.write_bytes(new_bytes)
        return len(original_bytes) - len(new_bytes)


class ASTStripper(BaseStripper):
    def _collect_comments(self, source_bytes: bytes) -> List[Tuple[int, int, bytes]]:
        code_str = source_bytes.decode("utf-8")
        lines = io.StringIO(code_str).readlines()
        byte_offsets = [0]
        for line in lines:
            byte_offsets.append(byte_offsets[-1] + len(line.encode("utf-8")))

        edits = []
        for token in tokenize.generate_tokens(io.StringIO(code_str).readline):
            if token.type != tokenize.COMMENT:
                continue
            line_num, col_offset = token.start
            if self._keep_comment(token.string, line_num - 1):
                continue

            line = lines[line_num - 1]
            start_offset = byte_offsets[line_num - 1]
            comment_start = start_offset + len(line[:col_offset].encode("utf-8"))
            comment_end = start_offset + len(line[: token.end[1]].encode("utf-8"))

            if not source_bytes[start_offset:comment_start].strip(b" \t"):
                edits.append((start_offset, self._line_end(source_bytes, comment_end), b""))
            else:
                curr = comment_start
                while curr > start_offset and source_bytes[curr - 1 : curr] in (b" ", b"\t"):
                    curr -= 1
                edits.append((curr, comment_end, b""))
        return edits

    def _collect_docstrings(self, source_bytes: bytes, tree: py_ast.AST) -> List[Tuple[int, int, bytes]]:
        code_bytes_lines = io.BytesIO(source_bytes).readlines()
        byte_offsets = [0]
        for line in code_bytes_lines:
            byte_offsets.append(byte_offsets[-1] + len(line))

        edits = []
        for node in py_ast.walk(tree):
            if not isinstance(node, (py_ast.Module, py_ast.FunctionDef, py_ast.AsyncFunctionDef, py_ast.ClassDef)):
                continue
            if isinstance(node, py_ast.Module):
                if self.preserve and not self.strip_all:
                    continue
            if not node.body:
                continue

            first_child = node.body[0]
            if not (
                isinstance(first_child, py_ast.Expr)
                and isinstance(first_child.value, py_ast.Constant)
                and isinstance(first_child.value.value, str)
            ):
                continue
            if first_child.end_lineno is None or first_child.end_col_offset is None:
                continue

            start_pos = byte_offsets[first_child.lineno - 1] + first_child.col_offset
            end_pos = byte_offsets[first_child.end_lineno - 1] + first_child.end_col_offset
            line_start = self._line_start(source_bytes, start_pos)
            line_end = self._line_end(source_bytes, end_pos)

            is_standalone = (
                not source_bytes[line_start:start_pos].strip() and not source_bytes[end_pos:line_end].strip()
            )
            has_second_docstring = (
                len(node.body) > 1
                and isinstance(node.body[1], py_ast.Expr)
                and isinstance(node.body[1].value, py_ast.Constant)
                and isinstance(node.body[1].value.value, str)
            )

            if isinstance(node, py_ast.Module):
                edits.append((start_pos, end_pos, b""))
            elif is_standalone and not has_second_docstring and len(node.body) == 1:
                # Sole node in body -> replace with pass
                edits.append((start_pos, end_pos, b"pass"))
            else:
                edits.append((line_start, line_end, b""))
        return edits

    def strip(self, code: str) -> str:
        tree = py_ast.parse(code)
        source_bytes = code.encode("utf-8")

        if self.strip_docstrings:
            source_bytes = self._apply_edits(source_bytes, self._collect_docstrings(source_bytes, tree))
            if self.strip_comments and b"#" in source_bytes:
                tree = py_ast.parse(source_bytes.decode("utf-8"))

        if self.strip_comments and b"#" in source_bytes:
            source_bytes = self._apply_edits(source_bytes, self._collect_comments(source_bytes))

        cleaned_code = source_bytes.decode("utf-8")
        if self.remove_blank_lines:
            cleaned_code = self._remove_blank_lines_ast(cleaned_code)
        elif cleaned_code != code:
            py_ast.parse(cleaned_code)
        return cleaned_code


class TSStripper(ASTStripper):
    def __init__(
        self,
        strip_comments: bool = False,
        strip_docstrings: bool = False,
        remove_blank_lines: bool = False,
        strip_all: bool = False,
        preserve: bool = True,
    ):
        super().__init__(strip_comments, strip_docstrings, remove_blank_lines, strip_all, preserve)
        import tree_sitter
        import tree_sitter_python

        self._parser = tree_sitter.Parser(tree_sitter.Language(tree_sitter_python.language()))

    def _collect_comments(self, source_bytes: bytes) -> List[Tuple[int, int, bytes]]:
        edits = []
        cursor = self._parser.parse(source_bytes).walk()
        while True:
            node = cursor.node
            has_child = True
            if node is not None and node.type == "comment":
                has_child = False
                comment_text = source_bytes[node.start_byte : node.end_byte].decode("utf-8")
                if not self._keep_comment(comment_text, node.start_point.row):
                    line_start = self._line_start(source_bytes, node.start_byte)
                    if not source_bytes[line_start : node.start_byte].strip(b" \t"):
                        edits.append((line_start, self._line_end(source_bytes, node.end_byte), b""))
                    else:
                        start_pos = node.start_byte
                        while start_pos and source_bytes[start_pos - 1 : start_pos] in (b" ", b"\t"):
                            start_pos -= 1
                        edits.append((start_pos, node.end_byte, b""))
            if has_child and cursor.goto_first_child():
                continue
            while not cursor.goto_next_sibling():
                if not cursor.goto_parent():
                    return edits


class CSTStripper(ASTStripper):
    def strip(self, code: str) -> str:
        import libcst as cst

        preserve = self.preserve
        strip_all = self.strip_all
        strip_comments = self.strip_comments
        strip_docstrings = self.strip_docstrings

        class CommentTransformer(cst.CSTTransformer):
            def __init__(self):
                super().__init__()
                self._header_comments = set()

            def on_visit(self, node):
                if preserve and not strip_all and hasattr(node, "header"):
                    for idx, line in enumerate(node.header[:2]):
                        comment = line.comment
                        if comment is not None and (
                            idx == 0
                            and comment.value.startswith("#!")
                            or BaseStripper.COOKIE_RE.search(comment.value.encode("utf-8"))
                        ):
                            self._header_comments.add(id(comment))
                return True

            def leave_Comment(self, original_node, updated_node):
                if (
                    preserve
                    and not strip_all
                    and (
                        id(original_node) in self._header_comments
                        or BaseStripper.DIRECTIVE_RE.match(original_node.value)
                    )
                ):
                    return updated_node
                return cst.RemoveFromParent()

            def leave_TrailingWhitespace(self, original_node, updated_node):
                if updated_node.comment is not None and not self._keep_comment_cst(updated_node.comment):
                    return updated_node.with_changes(comment=None, whitespace=cst.SimpleWhitespace(""))
                return updated_node

            def _keep_comment_cst(self, comment):
                if strip_all or not preserve:
                    return False
                return bool(BaseStripper.DIRECTIVE_RE.match(comment.value))

        class DocstringTransformer(cst.CSTTransformer):
            @staticmethod
            def _is_docstring(node) -> bool:
                if not isinstance(node, cst.Expr):
                    return False
                if not isinstance(node.value, (cst.SimpleString, cst.ConcatenatedString)):
                    return False
                try:
                    val = py_ast.literal_eval(cst.Module([]).code_for_node(node.value))
                except (ValueError, SyntaxError):
                    return False
                return isinstance(val, str)

            def leave_Module(self, original_node, updated_node):
                if preserve and not strip_all:
                    return updated_node
                if updated_node.body and self._is_docstring(updated_node.body[0]):
                    return updated_node.with_changes(body=updated_node.body[1:])
                return updated_node

            def leave_FunctionDef(self, original_node, updated_node):
                return self._strip_suite(updated_node)

            def leave_AsyncFunctionDef(self, original_node, updated_node):
                return self._strip_suite(updated_node)

            def leave_ClassDef(self, original_node, updated_node):
                return self._strip_suite(updated_node)

            def _strip_suite(self, node):
                body_seq = node.body.body
                if body_seq and self._is_docstring(body_seq[0]):
                    items = list(body_seq)
                    new_body = [cst.SimpleStatementLine([cst.Pass()])] if len(items) == 1 else items[1:]
                    return node.with_changes(body=node.body.with_changes(body=new_body))
                return node

        py_ast.parse(code)
        module = cst.parse_module(code)

        if strip_docstrings:
            module = module.visit(DocstringTransformer())
        if strip_comments:
            module = module.visit(CommentTransformer())

        cleaned_code = module.code
        if self.remove_blank_lines:
            cleaned_code = self._remove_blank_lines_ast(cleaned_code)
        else:
            py_ast.parse(cleaned_code)
        return cleaned_code
