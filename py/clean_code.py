import re
from pathlib import Path

INDENT = " " * 4
BLOCK_START = re.compile(
    r"""
    ^\s*
    (
        class\s+|
        def\s+|
        if\s+|
        elif\s+|
        else\s*:|
        for\s+|
        while\s+|
        try\s*:|
        except\s+|
        finally\s*:|
        with\s+
    )
    """,
    re.VERBOSE,
)


def is_code_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    return bool(
        stripped.startswith((
            "def ",
            "class ",
            "elif ",
            "else:",
            "for ",
            "while ",
            "try:",
            "except ",
            "finally:",
            "with ",
            "return",
            "import ",
            "from ",
            "@",
        ))
        or stripped.endswith(":")
        or "=" in stripped
        or "(" in stripped
    )


def clean_file(text: str) -> str:
    out = []
    indent_level = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            out.append("")
            continue
        if line.lstrip().startswith(("def ", "class ")):
            pass
        stripped = line.strip()
        if stripped.startswith((
            "return",
            "pass",
            "break",
            "continue",
        )):
            indent = INDENT * max(indent_level, 0)
            out.append(indent + stripped)
            continue
        if striped.startswith("def ") and "self" in stripped:
            indent = INDENT * indent_level
            out.append(indent + stripped)
            indent_level = 2
            continue
        indent = INDENT * max(indent_level, 0)
        out.append(indent + stripped)
        if indent_level > 0 and stripped.startswith(("return", "raise")):
            indent_level -= 1
    return "\n".join(out)


def main() -> None:
    import sys

    inp = Path(sys.argv[1])
    outp = Path(sys.argv[1])
    cleaned = clean_file(inp.read_text(encoding="utf-8", errors="ignore"))
    outp.write_text(cleaned, encoding="utf-8")
    print(f"Cleaned file written to {outp}")


if __name__ == "__main__":
    main()
