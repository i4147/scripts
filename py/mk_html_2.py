import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Final, Optional
from loguru import logger

RST2HTML_OPTIONS = "--no-toc-backlinks --strip-comments --language en --date"
VALID_EXTENSIONS = {".rst", ".txt", ".md"}
MD_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
MD_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
MD_CODE_BLOCK_PATTERN = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
FIXED_WORKERS = 8


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


def convert_md_to_rst(content):
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
        indented = "\n".join("    " + line for line in code.split("\n"))
        if language:
            return f".. code-block:: {language}\n\n{indented}\n"
        else:
            return f"::\n\n{indented}\n"

    content = MD_CODE_BLOCK_PATTERN.sub(replace_code_block, content)
    content = re.sub(r"\*\*(.+?)\*\*", r"**\1**", content)
    content = re.sub(r"\*(.+?)\*", r"*\1*", content)
    content = re.sub(r"`([^`]+)`", r"``\1``", content)
    content = re.sub(r"^---$", "-------", content, flags=re.MULTILINE)
    content = re.sub(r"^\* ", r"- ", content, flags=re.MULTILINE)
    return content


def convert_file_to_html(path, stylesheet_url=None):
    try:
        html_path = path.with_suffix(".html")
        if html_path.exists() and html_path.stat().st_mtime > path.stat().st_mtime:
            return html_path
        content = path.read_text(encoding="utf-8")
        cleanup_temp = False
        temp_file = None
        if path.suffix.lower() == ".md":
            content = convert_md_to_rst(content)
            temp_file = path.with_suffix(".rst")
            temp_file.write_text(content, encoding="utf-8")
            path = temp_file
            cleanup_temp = True
        cmd = [
            sys.executable,
            "-m",
            "docutils.__main__",
            str(path),
            str(html_path),
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
                cmd.extend([str(path), str(html_path)])
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
            else:
                raise RuntimeError("No RST to HTML converter found")
        if cleanup_temp and temp_file is not None and temp_file.exists():
            temp_file.unlink()
        return html_path
    except Exception as e:
        logger.error(f"Error converting {path}: {e}")
        return None


def generate_stylesheet_hash(stylesheet_path):
    if not stylesheet_path or not stylesheet_path.exists():
        return "style.css"
    with open(stylesheet_path, "rb") as f:
        css = f.read()
    checksum = hashlib.sha256(css).hexdigest()[:32]
    return f"style_{checksum}.css"


def process_file(args):
    path, stylesheet_url = args
    html_path = convert_file_to_html(path, stylesheet_url)
    return (path, html_path)


def find_all_source_files(root_dir=None):
    if root_dir is None:
        root_dir = Path.cwd()
    source_files = []
    for ext in VALID_EXTENSIONS:
        source_files.extend(root_dir.rglob(f"*{ext}"))
    return source_files


def publish_parallel(root_dir=None, max_workers=None):
    if root_dir is None:
        root_dir = Path.cwd()
    root_dir = Path(root_dir).resolve()
    stylesheet_path = root_dir / "style.css"
    stylesheet_url = None
    if stylesheet_path.exists():
        stylesheet_filename = generate_stylesheet_hash(stylesheet_path)
        stylesheet_dest = root_dir / stylesheet_filename
        if not stylesheet_dest.exists():
            shutil.copy(stylesheet_path, stylesheet_dest)
        stylesheet_url = stylesheet_filename
    source_files = find_all_source_files(root_dir)
    if not source_files:
        print(f"No source files found in {root_dir}")
        return
    print(f"Found {len(source_files)} files to convert")
    converted = 0
    errors = 0
    worker_args = [(fp, stylesheet_url) for fp in source_files]
    with Pool(processes=FIXED_WORKERS) as pool:
        async_results = [pool.apply_async(process_file, (arg,)) for arg in worker_args]
        pool.close()
        pool.join()
        for async_result in async_results:
            try:
                original, html_path = async_result.get()
                if html_path:
                    converted += 1
                    print(f"Converted: {original.relative_to(root_dir)} -> {html_path.relative_to(root_dir)}")
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                logger.error(f"Error processing file: {e}")
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
        "--force",
        action="store_true",
        help="Force re-conversion even if HTML is newer",
    )
    args = parser.parse_args()
    root_dir = Path(args.directory).resolve()
    if not root_dir.exists():
        logger.error(f"Error: Directory '{root_dir}' does not exist")
        return 1
    publish_parallel(root_dir, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
