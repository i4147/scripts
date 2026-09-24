import re
import sys
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Final

TARGET_NAMES = frozenset({"PKGINFO", "METADATA", "PKG-INFO"})
TARGET_EXTENSIONS = frozenset({".md", ".txt", ".html"})
MAX_WORKERS = 8
OUTPUT_DIR = Path("extracted_code")
PY_CODE_BLOCK = re.compile(
    r"```python\s*\n(.*?)```" r"\"\"\"(.*?)\"\"\"",
    re.DOTALL | re.IGNORECASE,
)
INLINE_PY = re.compile(
    r"(?:^|\n)((?:import\s+\w+|from\s+\w+\s+import|def\s+\w+|class\s+\w+).*?)"
    r"(?=\n\s*\n|\Z)",
    re.DOTALL | re.MULTILINE,
)
REPL_SESSION = re.compile(
    r"(?:^|\n)((?:>>>|\.\.\.).*?)(?=\n\s*\n|\Z)",
    re.DOTALL | re.MULTILINE,
)
ProcessResult = tuple[Path, list[Path]]


def _is_target(file_path):
    if file_path.name in TARGET_NAMES:
        return True
    return file_path.suffix.lower() in TARGET_EXTENSIONS


def find_target_files(paths):
    found = set()
    for p in paths:
        path = Path(p)
        if path.is_file():
            if _is_target(path):
                found.add(path)
        elif path.is_dir():
            for candidate in path.rglob("*"):
                if candidate.is_file() and _is_target(candidate):
                    found.add(candidate)
    return sorted(found)


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


def extract_python_blocks(file_path):
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
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
    if not blocks and file_path.name in TARGET_NAMES:
        for match in INLINE_PY.finditer(content):
            code = match.group(1).strip()
            if code and ("import" in code or "def " in code or "class " in code):
                blocks.append(code)
    return blocks


def process_file(file_path, output_dir):
    blocks = extract_python_blocks(file_path)
    saved = []
    for idx, code in enumerate(blocks, 1):
        stem = file_path.stem.replace(" ", "_")
        out_name = f"{stem}_{idx:03d}.py"
        out_path = output_dir / out_name
        header = f"# Source: {file_path}\n# Block: {idx}\n# Extracted: {file_path.name}\n\n"
        out_path.write_text(header + code + "\n", encoding="utf-8")
        saved.append(out_path)
    return file_path, saved


def main():
    input_paths = sys.argv[1:] if len(sys.argv) > 1 else ["."]
    OUTPUT_DIR.mkdir(exist_ok=True)
    target_files = find_target_files(input_paths)
    if not target_files:
        print("No target files found.")
        return
    print(f"Found {len(target_files)} target files. Processing...")
    results = []
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(process_file, (f, OUTPUT_DIR)) for f in target_files]
        for async_res in async_results:
            file_path, saved = async_res.get()
            results.append((file_path, saved))
            print(f"  ✓ {file_path}: {len(saved)} block(s) extracted")
    total_blocks = sum(len(saved) for _, saved in results)
    print(f"Done! Extracted {total_blocks} Python block(s) to '{OUTPUT_DIR}/'")
    print("Reference headers in each file indicate the source.")


if __name__ == "__main__":
    raise SystemExit(main())
