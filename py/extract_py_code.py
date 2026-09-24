from __future__ import annotations

import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

TARGET_NAMES = {"PKGINFO", "METADATA", "PKG-INFO"}
TARGET_EXTENSIONS = {".md", ".txt", ".html"}
PY_CODE_BLOCK = re.compile(
    r"```python\s*\n(.*?)```" r"\"\"\"(.*?)\"\"\"",
    re.DOTALL | re.IGNORECASE,
)
INLINE_PY = re.compile(
    r"(?:^|\n)((?:import\s+\w+|from\s+\w+\s+import|def\s+\w+|class\s+\w+).*?)(?=\n\s*\n|\Z)",
    re.DOTALL | re.MULTILINE,
)
REPL_SESSION = re.compile(
    r"(?:^|\n)((?:>>>|\.\.\.).*?)(?=\n\s*\n|\Z)",
    re.DOTALL | re.MULTILINE,
)


def find_target_files(paths):
    files = []
    for p in paths:
        path = Path(p)
        if path.is_file():
            if _is_target(path):
                files.append(path)
        elif path.is_dir():
            for f in path.rglob("*"):
                if f.is_file() and _is_target(f):
                    files.append(f)
    return files


def _is_target(path):
    if path.name in TARGET_NAMES:
        return True
    return path.suffix.lower() in TARGET_EXTENSIONS


def parse_repl_block(block):
    lines = block.strip().split("\n")
    result_lines = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith((">>>", "...")):
            code = stripped[3:].strip()
            result_lines.append(code)
            in_code = True
        elif in_code and stripped:
            result_lines.append(f"# {stripped}")
        elif not stripped:
            result_lines.append("")
    return "\n".join(result_lines)


def extract_python_blocks(path):
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return []
    blocks = []
    for match in PY_CODE_BLOCK.finditer(content):
        code = match.group(1).strip()
        if code:
            if ">>>" in code:
                code = parse_repl_block(code)
            blocks.append(code)
    for match in REPL_SESSION.finditer(content):
        code = parse_repl_block(match.group(1))
        if code.strip():
            blocks.append(code)
    if not blocks and path.name in TARGET_NAMES:
        for match in INLINE_PY.finditer(content):
            code = match.group(1).strip()
            if code and ("import" in code or "def " in code or "class " in code):
                blocks.append(code)
    return blocks


def process_file(path, output_dir):
    blocks = extract_python_blocks(path)
    saved = []
    for idx, code in enumerate(blocks, 1):
        stem = path.stem.replace(" ", "_")
        out_name = f"{stem}_{idx:03d}.py"
        out_path = output_dir / out_name
        header = f"# Source: {path}\n# Block: {idx}\n# Extracted: {path.name}\n\n"
        out_path.write_text(header + code + "\n", encoding="utf-8")
        saved.append(out_path)
    return path, saved


def main():
    if len(sys.argv) > 1:
        input_paths = sys.argv[1:]
    else:
        input_paths = ["."]
    output_dir = Path("extracted_code")
    output_dir.mkdir(exist_ok=True)
    target_files = find_target_files(input_paths)
    if not target_files:
        print("No target files found.")
        return
    print(f"Found {len(target_files)} target files. Processing...")
    results = []
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(process_file, f, output_dir): f for f in target_files}
        for future in as_completed(futures):
            path, saved = future.result()
            results.append((path, saved))
            print(f"  ✓ {path}: {len(saved)} block(s) extracted")
    total_blocks = sum(len(saved) for _, saved in results)
    print(f"\nDone! Extracted {total_blocks} Python block(s) to '{output_dir}/'")
    print("Reference headers in each file indicate the source.")


if __name__ == "__main__":
    raise SystemExit(main())
