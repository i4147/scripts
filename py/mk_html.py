from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

RST2HTML_OPTIONS = "--no-toc-backlinks --strip-comments --language en --date"
VALID_EXTENSIONS = {".rst", ".txt", ".md"}
MD_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
MD_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
MD_CODE_BLOCK_PATTERN = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)


def find_rst2html_script():
    possible_paths = [
        Path.cwd() / "doc" / "rest2html.py",
        Path.cwd() / "rest2html.py",
        Path(sys.prefix) / "doc" / "rest2html.py",
    ]
    for path in possible_paths:
        if path.exists():
            return path
    return None


def convert_md_to_rst(content: str) -> str:
    def replace_heading(match):
        level = len(match.group(1))
        text = match.group(2).strip()
        if level == 1:
            return f"{'=' * len(text)}\n{text}\n{'=' * len(text)}"
        elif level == 2:
            return f"{text}\n{'-' * len(text)}"
        else:
            char = "~^+"[min(level - 3, 2)]
            return f"{text}\n{char * len(text)}"

    content = MD_HEADING_PATTERN.sub(replace_heading, content)
    content = MD_LINK_PATTERN.sub(r"`\1 <\2>`_", content)

    def replace_code_block(match):
        language = match.group(1)
        code = match.group(2).strip()
        if language:
            return f".. code-block:: {language}\n\n    {chr(10).join('    ' + line for line in code.split(chr(10)))}\n"
        else:
            return f"::\n\n    {chr(10).join('    ' + line for line in code.split(chr(10)))}\n"

    content = MD_CODE_BLOCK_PATTERN.sub(replace_code_block, content)
    content = re.sub(r"\*\*(.+?)\*\*", r"**\1**", content)
    content = re.sub(r"\*(.+?)\*", r"*\1*", content)
    content = re.sub(r"`([^`]+)`", r"``\1``", content)
    content = re.sub(r"^---$", "-------", content, flags=re.MULTILINE)
    content = re.sub(r"^\* ", r"- ", content, flags=re.MULTILINE)
    return content


def convert_file_to_html(file_path: Path, stylesheet_url: str | None = None) -> Path:
    try:
        html_path = file_path.with_suffix(".html")
        if html_path.exists() and html_path.stat().st_mtime > file_path.stat().st_mtime:
            return html_path
        content = file_path.read_text(encoding="utf-8")
        if file_path.suffix.lower() == ".md":
            content = convert_md_to_rst(content)
            temp_file = file_path.with_suffix(".rst")
            temp_file.write_text(content, encoding="utf-8")
            file_path = temp_file
            cleanup_temp = True
        else:
            cleanup_temp = False
        cmd = [
            sys.executable,
            "-m",
            "docutils.__main__",
            file_path,
            html_path,
        ]
        if stylesheet_url:
            cmd.extend(["--stylesheet", stylesheet_url, "--link-stylesheet"])
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        except (subprocess.CalledProcessError, FileNotFoundError):
            rst2html_script = find_rst2html_script()
            if rst2html_script:
                cmd = [
                    sys.executable,
                    str(rst2html_script),
                ] + RST2HTML_OPTIONS.split()
                if stylesheet_url:
                    cmd.extend(["--stylesheet", stylesheet_url, "--link-stylesheet"])
                cmd.extend([str(file_path), str(html_path)])
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
            else:
                raise RuntimeError("No RST to HTML converter found")
        if cleanup_temp and file_path.exists():
            file_path.unlink()
        return html_path
    except Exception as e:
        print(f"Error converting {file_path}: {e}", file=sys.stderr)
        return None


def generate_stylesheet_hash(stylesheet_path: Path) -> str:
    if not stylesheet_path or not stylesheet_path.exists():
        return "style.css"
    with open(stylesheet_path, "rb") as f:
        css = f.read()
    checksum = hashlib.sha256(css).hexdigest()[:32]
    return f"style_{checksum}.css"


def process_file(file_path: Path, stylesheet_url: str | None = None) -> tuple:
    html_path = convert_file_to_html(file_path, stylesheet_url)
    return (file_path, html_path)


def find_all_source_files(root_dir: Path | None = None) -> list:
    if root_dir is None:
        root_dir = Path.cwd()
    source_files = []
    for ext in VALID_EXTENSIONS:
        source_files.extend(root_dir.rglob(f"*{ext}"))
    return source_files


def publish_parallel(root_dir: Path | None = None, max_workers: int | None = None):
    if root_dir is None:
        root_dir = Path.cwd()
    root_dir = Path(root_dir).resolve()
    stylesheet_path = root_dir / "style.css"
    if stylesheet_path.exists():
        stylesheet_filename = generate_stylesheet_hash(stylesheet_path)
        stylesheet_dest = root_dir / stylesheet_filename
        if not stylesheet_dest.exists():
            shutil.copy(stylesheet_path, stylesheet_dest)
        stylesheet_url = stylesheet_filename
    else:
        stylesheet_url = None
    source_files = find_all_source_files(root_dir)
    if not source_files:
        print(f"No source files found in {root_dir}")
        return
    print(f"Found {len(source_files)} files to convert")
    converted = 0
    errors = 0
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(process_file, file_path, stylesheet_url): file_path for file_path in source_files
        }
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                original, html_path = future.result()
                if html_path:
                    converted += 1
                    print(f"Converted: {original.relative_to(root_dir)} -> {html_path.relative_to(root_dir)}")
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                print(
                    f"Error processing {file_path.relative_to(root_dir)}: {e}",
                    file=sys.stderr,
                )
    print(f"\nConversion complete: {converted} converted, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description="Convert all .rst, .txt, and .md files to HTML recursively")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Root directory to process (default: current directory)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=os.cpu_count(),
        help="Number of parallel workers (default: CPU count)",
    )
    parser.add_argument("--force", action="store_true", help="Force re-conversion even if HTML is newer")
    args = parser.parse_args()
    root_dir = Path(args.directory).resolve()
    if not root_dir.exists():
        print(f"Error: Directory '{root_dir}' does not exist", file=sys.stderr)
        sys.exit(1)
    publish_parallel(root_dir, args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
