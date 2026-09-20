
import os
import sys
import argparse
from pathlib import Path

try:
    from docutils.writers import UnfilteredWriter
except ImportError:
    print("Error: docutils is required. Install with: pip install docutils")
    sys.exit(1)

try:
    import mistletoe
except ImportError:
    print("Error: mistletoe is required. Install with: pip install mistletoe")
    sys.exit(1)


class RstToMarkdownWriter(UnfilteredWriter):

    supported = ("markdown", "md")
    output = None

    def __init__(self) -> None:
        super().__init__()
        self.output = ""

    def translate(self) -> None:
        
        from docutils.core import publish_parts

        parts = publish_parts(self.document.source, writer_name="html", settings_overrides={"initial_header_level": 2})
        html_content = parts["html_body"]

        
        from mistletoe import Document

        doc = Document(html_content)
        self.output = doc.__repr__()


def rst_to_markdown(content: str):
    from docutils.core import publish_parts
    import tempfile

    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".rst", delete=False) as f:
        f.write(content)
        temp_file = f.name

    try:
        
        parts = publish_parts(
            source=content, writer_name="html", settings_overrides={"initial_header_level": 2, "warning_stream": None}
        )
        html_content = parts["html_body"]

        
        from mistletoe import html_to_markdown

        markdown_content = html_to_markdown(html_content)

        return markdown_content
    finally:
        
        if os.path.exists(temp_file):
            os.unlink(temp_file)


def convert_file(filepath: Path, backup=True) -> bool:
    filepath = Path(filepath)

    if not filepath.exists():
        print(f"Error: {filepath} not found")
        return False

    if filepath.suffix.lower() != ".rst":
        print(f"Skipping {filepath}: not an .rst file")
        return False

    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            rst_content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return False

    
    try:
        markdown_content = rst_to_markdown(rst_content)
    except Exception as e:
        print(f"Error converting {filepath}: {e}")
        return False

    
    if backup:
        backup_path = filepath.with_suffix(".rst.bak")
        try:
            import shutil

            shutil.copy2(filepath, backup_path)
            print(f"Backup created: {backup_path}")
        except Exception as e:
            print(f"Warning: could not create backup: {e}")

    
    md_path = filepath.with_suffix(".md")
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        
        

        print(f"Converted: {filepath} -> {md_path}")
        return True
    except Exception as e:
        print(f"Error writing {md_path}: {e}")
        return False


def convert_recursive(directory: Path, backup: bool = True) -> None:
    directory = Path(directory)
    if not directory.exists():
        print(f"Error: {directory} not found")
        return

    rst_files = list(directory.rglob("*.rst"))
    if not rst_files:
        print(f"No .rst files found in {directory}")
        return

    print(f"Found {len(rst_files)} .rst files")
    success_count = 0

    for rst_file in rst_files:
        if convert_file(rst_file, backup):
            success_count += 1

    print(f"\nConverted {success_count}/{len(rst_files)} files")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert .rst files to .md in-place",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python rst_to_md.py file1.rst file2.rst
  python rst_to_md.py --recursive docs/
  python rst_to_md.py --no-backup file.rst
  python rst_to_md.py --remove-original file.rst
        """,
    )

    parser.add_argument("paths", nargs="+", help="Files or directories to convert")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recursively process directories")
    parser.add_argument("--no-backup", default=True, action="store_true", help="Do not create backup files")
    parser.add_argument(
        "--remove-original", default=True, action="store_true", help="Remove original .rst files after conversion"
    )

    args = parser.parse_args()

    backup = not args.no_backup

    for path in args.paths:
        path_obj = Path(path)

        if path_obj.is_dir():
            if args.recursive:
                convert_recursive(path_obj, backup)
            else:
                print(f"Skipping directory {path}. Use --recursive to process directories.")
        elif path_obj.is_file():
            if convert_file(path_obj, backup) and args.remove_original:
                path_obj.unlink()
                print(f"Removed original: {path_obj}")
        else:
            print(f"Error: {path} is not a valid file or directory")


if __name__ == "__main__":
    main()
