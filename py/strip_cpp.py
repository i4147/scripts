from __future__ import annotations

import concurrent.futures
import re
from pathlib import Path

COMMENT_RE = re.compile(
    r"(?://[^\n]*|/\*.*?\*/)|(?:\"(?:\\[\s\S]|[^\"\\])*\"|\'(?:\\[\s\S]|[^\'\\])*\')",
    re.DOTALL,
)


def strip_comments_from_text(text: str) -> str:
    def replacer(match):
        group = match.group(0)
        if group.startswith(("/", "/*")):
            return ""
        return group

    return COMMENT_RE.sub(replacer, text)


def process_file(file_path: Path) -> str:
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        cleaned_content = strip_comments_from_text(content)
        if content != cleaned_content:
            file_path.write_text(cleaned_content, encoding="utf-8")
            return f"Cleaned: {file_path}"
        return f"No comments found: {file_path}"
    except Exception as e:
        return f"Error processing {file_path}: {e}"


def main():
    extensions = {".h", ".c", ".cpp", ".hpp"}
    current_dir = Path(".")
    files_to_process = [p for p in current_dir.rglob("*") if p.suffix.lower() in extensions]
    if not files_to_process:
        print("No matching C/C++ files found.")
        return
    print(f"Found {len(files_to_process)} files. Processing in parallel...")
    with concurrent.futures.ProcessPoolExecutor() as executor:
        results = executor.map(process_file, files_to_process)
        for result in results:
            print(result)


if __name__ == "__main__":
    raise SystemExit(main())
