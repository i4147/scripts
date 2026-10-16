from __future__ import annotations

import shutil
import sys
import textwrap
from pathlib import Path


def wrap_file_content(path: Path, width: int) -> None:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Error: File '{path}' not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)
    wrapped_lines = []
    paragraphs = content.split("\n\n")
    for paragraph in paragraphs:
        lines = paragraph.split("\n")
        for _i, line in enumerate(lines):
            if line.strip():
                wrapped = textwrap.wrap(
                    line,
                    width=width,
                    break_long_words=False,
                    break_on_hyphens=False,
                    replace_whitespace=False,
                    drop_whitespace=True,
                )
                wrapped_lines.extend(wrapped if wrapped else [""])
            else:
                wrapped_lines.append("")
        if paragraph != paragraphs[-1]:
            wrapped_lines.append("")
    try:
        path.write_text("\n".join(wrapped_lines) + "\n", encoding="utf-8")
        print(f"Successfully wrapped '{path}' to {width} characters wide.")
    except Exception as e:
        print(f"Error writing file: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path>", file=sys.stderr)
        sys.exit(1)
    path = Path(sys.argv[1])
    try:
        terminal_width = shutil.get_terminal_size().columns
    except Exception:
        terminal_width = 80
        print(f"Warning: Could not determine terminal width. Using {terminal_width} columns.")
    terminal_width = max(terminal_width, 20)
    wrap_file_content(path, terminal_width)


if __name__ == "__main__":
    raise SystemExit(main())
