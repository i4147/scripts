from __future__ import annotations
import tree_sitter
import tree_sitter_python

# An edit is (start_byte, end_byte, replacement_bytes).
# end_byte is exclusive; replacement is usually b"" (pure deletion).
_Edit = tuple[int, int, bytes]


class TreeSitterStripper:
    """Structure-preserving comment & docstring stripper.
    Everything is done by editing byte ranges of the original UTF-8 source,
    so indentation, line endings (LF/CRLF), quoting, parentheses, and any
    other formatting are preserved exactly. The only structural change is
    that a docstring which is the sole statement of a block is rewritten to
    `pass` (in place, keeping the original indent) so the block stays valid.
    Parameters
    ----------
    strip_comments : bool
    strip_docstrings : bool
    preserve_shebangs : bool
        Keep a leading ``#!...`` line if it is the very first byte of the file.
    preserve_module_docstring : bool
        Keep the module-level docstring even when stripping docstrings.
    """

    name = "tree-sitter"

    def __init__(
        self,
        strip_comments: bool = True,
        strip_docstrings: bool = True,
        preserve_shebangs: bool = False,
        preserve_module_docstring: bool = False,
    ) -> None:
        self.strip_comments = strip_comments
        self.strip_docstrings = strip_docstrings
        self.preserve_shebangs = preserve_shebangs
        self.preserve_module_docstring = preserve_module_docstring
        # Support both the pre-0.22 and >=0.22 tree_sitter APIs.
        try:
            self._language = tree_sitter.Language(tree_sitter_python.language())
            self._parser = tree_sitter.Parser(self._language)
        except TypeError:
            self._language = None
            self._parser = tree_sitter.Parser()
            self._parser.set_language(tree_sitter_python.language())

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def strip(self, source: str) -> str:
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

    # ------------------------------------------------------------------ #
    # Position helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _line_start(src: bytes, pos: int) -> int:
        """Index of the first byte on the line containing `pos`."""
        idx = src.rfind(b"\n", 0, pos)
        return 0 if idx < 0 else idx + 1

    @staticmethod
    def _line_end(src: bytes, pos: int) -> int:
        """Index just past the newline that terminates the line containing
        `pos` (or len(src) if the file has no trailing newline)."""
        idx = src.find(b"\n", pos)
        return len(src) if idx < 0 else idx + 1

    # ------------------------------------------------------------------ #
    # Comment collection
    # ------------------------------------------------------------------ #
    def _collect_comments(self, node, src: bytes, edits: list[_Edit]) -> None:
        if node.type == "comment":
            # Shebang: only the very first byte of the file qualifies.
            if self.preserve_shebangs and node.start_byte == 0 and src.startswith(b"#!"):
                return
            line_start = self._line_start(src, node.start_byte)
            before = src[line_start : node.start_byte]
            if before.strip(b" \t") == b"":
                # Full-line comment: delete the whole line including the
                # trailing newline, so no blank line is left behind.
                start = line_start
                end = self._line_end(src, node.end_byte)
            else:
                # Trailing comment: delete from the end of the preceding
                # code (skipping any whitespace) up to the end of the
                # comment, so `x = 1  # c` becomes `x = 1`.
                i = node.start_byte - 1
                while i >= line_start and src[i : i + 1] in (b" ", b"\t"):
                    i -= 1
                start = i + 1
                end = node.end_byte
            edits.append((start, end, b""))
            return
        for child in node.children:
            self._collect_comments(child, src, edits)

    # ------------------------------------------------------------------ #
    # Docstring collection
    # ------------------------------------------------------------------ #
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
                    # Single-line body: `def f(): "doc"`
                    edits.append((body.start_byte, body.end_byte, b"pass"))
        # Recurse into every child; the recursion will find nested
        # function/class definitions inside these bodies as well.
        for child in node.children:
            self._collect_docstrings(child, src, edits)

    @staticmethod
    def _is_string_expr(stmt) -> bool:
        """True if `stmt` is an expression_statement whose only named
        child is a string literal (or a concatenation of them)."""
        named = [c for c in stmt.children if c.is_named]
        return len(named) == 1 and named[0].type in ("string", "concatenated_string")

    @staticmethod
    def _first_statement(container):
        """First non-comment named child of a module or block."""
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
            # Rewrite the string literal in place to `pass` so the block
            # stays valid. Indentation is untouched because we only
            # replace the string's own bytes.
            edits.append((first.start_byte, first.end_byte, b"pass"))
        else:
            # Delete the whole line: leading indent, the docstring, any
            # trailing whitespace/comment, and the terminating newline.
            start = self._line_start(src, first.start_byte)
            end = self._line_end(src, first.end_byte)
            edits.append((start, end, b""))

    # ------------------------------------------------------------------ #
    # Edit application
    # ------------------------------------------------------------------ #
    @staticmethod
    def _merge(edits: list[_Edit], src: bytes) -> list[_Edit]:
        """Sort and coalesce overlapping or adjacent edits.
        When two edits are adjacent (or overlap), the replacement of the
        first wins unless it is empty, in which case the non-empty one is
        kept. This lets a `pass`-injection absorb an immediately following
        trailing-comment removal without losing the `pass`.
        """
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
