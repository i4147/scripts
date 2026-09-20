import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


def convert_file(input_path: Path, output_path: Optional[Path] = None) -> Path:
    input_path = Path(input_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"No such file: {input_path}")

    output_path = Path(output_path) if output_path else input_path.with_suffix(".md")

    subprocess.run(
        ["pandoc", "-f", "rst", "-t", "gfm", "--wrap=none", "-o", str(output_path), str(input_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return output_path


def convert_path(path: str, output: Optional[str] = None) -> list:
    path = Path(path)

    if path.is_dir():
        if output:
            raise ValueError("-o/--output only works when converting a single file")
        results = []
        for rst in sorted(path.rglob("*.rst")):
            md = convert_file(rst)
            print(f"converted: {rst} -> {md}")
            results.append(md)
        if not results:
            print(f"No .rst files found under {path}")
        return results

    md = convert_file(path, output)
    print(f"converted: {path} -> {md}")
    return [md]


SAMPLE_RST = """\
Sample Document
===============

A *quick* test of **RST** to ``Markdown`` conversion.

Section One
-----------

- item one
- item two

1. first
2. second

Code example::

    def hello():
        print("hi")

See `Python <https://www.python.org>`_ for more.
"""


def demo() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rst = Path(tmp) / "sample.rst"
        rst.write_text(SAMPLE_RST, encoding="utf-8")

        md = convert_file(rst)
        print(f"--- input: {rst.name} ---\n{SAMPLE_RST}")
        print(f"--- output: {md.name} ---\n{md.read_text(encoding='utf-8')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert .rst files to .md via pandoc")
    parser.add_argument("input", nargs="?", help="a .rst file or a directory to scan")
    parser.add_argument("-o", "--output", help="output file (single-file mode only)")
    args = parser.parse_args()

    if shutil.which("pandoc") is None:
        sys.exit("Error: pandoc is not installed. See https://pandoc.org/installing.html")

    if args.input is None:
        demo()
        return

    try:
        convert_path(args.input, args.output)
    except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Conversion failed: {exc}")


if __name__ == "__main__":
    main()
