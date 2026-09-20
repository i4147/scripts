from __future__ import annotations

import logging
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Final

from deep_translator import GoogleTranslator

SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"lazy", ".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
LANGUAGE_PATTERN: Final[re.Pattern] = re.compile(
    r"[\u0600-\u06FF\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF\uAC00-\uD7AF\u0400-\u04FF]"
)
MAX_WORKERS: Final[int] = 4
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def is_foreign_line(line: str) -> bool:
    return bool(LANGUAGE_PATTERN.search(line))


def process_file(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        translator = GoogleTranslator(source="auto", target="en")
        modified = False
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and is_foreign_line(stripped):
                try:
                    translated = translator.translate(stripped)
                    if translated:
                        indent = line[: len(line) - len(line.lstrip())]
                        ending = "\n" if line.endswith("\n") else ""
                        new_lines.append(f"{indent}{translated}{ending}")
                        modified = True
                    else:
                        new_lines.append(line)
                except Exception as e:
                    logger.error("Error translating line in %s: %s", path, e)
                    new_lines.append(line)
            else:
                new_lines.append(line)
        if modified:
            path.write_text("".join(new_lines), encoding="utf-8")
            return f"✓ Updated: {path}"
        return f"No changes: {path}"
    except Exception as e:
        return f"Error processing {path}: {e}"


def main() -> None:
    extensions: Final[list[str]] = ["*.txt", "*.md", "*.py", "*.json", "*.csv"]
    files_to_process: list[Path] = []
    cwd = Path(".")
    for ext in extensions:
        for path in cwd.rglob(ext):
            if any(part.startswith(".") or part in SKIP_DIRS for part in path.parts):
                continue
            if path.is_file():
                files_to_process.append(path)
    if not files_to_process:
        print("No files found to process.")
        return
    print("Starting processing of %d files...", len(files_to_process))
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_file, f): f for f in files_to_process}
        for future in as_completed(futures):
            print(future.result())


if __name__ == "__main__":
    raise SystemExit(main())
