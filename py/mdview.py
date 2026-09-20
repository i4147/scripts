from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown


def read_markdown(file_path: str) -> str:
    path = Path(file_path).expanduser()

    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    return path.read_text(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdview",
        description="View a Markdown file in the terminal.",
    )
    parser.add_argument(
        "file",
        type=str,
        help="Path to a Markdown file",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    console = Console()

    try:
        markdown_text = read_markdown(args.file)
    except FileNotFoundError as error:
        console.print(f"[red]Error:[/red] {error}", file=sys.stderr)
        return 1
    except PermissionError:
        console.print(
            f"[red]Error:[/red] Permission denied: {args.file}",
            file=sys.stderr,
        )
        return 1
    except UnicodeDecodeError:
        console.print(
            f"[red]Error:[/red] {args.file} is not a valid UTF-8 text file.",
            file=sys.stderr,
        )
        return 1
    except OSError as error:
        console.print(f"[red]Error:[/red] {error}", file=sys.stderr)
        return 1

    console.print(Markdown(markdown_text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
