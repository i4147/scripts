from __future__ import annotations
from argparse import Namespace
import argparse
import ast
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable
from tqdm import tqdm

IGNORED_DIRS = {".git", "dist", "build"}
CACHE_FILE = Path(".pyformat.cache")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def is_python_file(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    try:
        first_line = path.open("rb").readline(200)
        if first_line.startswith(b"#!") and b"python" in first_line.lower():
            return True
    except Exception:
        return False
    try:
        ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        return True
    except Exception:
        return False


def format_file(file: Path, *, use_black: bool, use_autopep: bool, use_isort: bool, remove_unused: bool) -> None:
    if remove_unused:
        run(["autoflake", "--in-place", "--remove-all-unused-imports", "--remove-unused-variables", str(file)])
    if use_isort:
        run(["isort", str(file)])
    if use_black:
        run(["black", "--quiet", str(file)])
    elif use_autopep:
        run(["autopep8", "--in-place", "--aggressive", str(file)])
    else:
        run(["yapf", "--in-place", str(file)])


def load_cache() -> dict[str, str]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_cache(cache: dict[str, str]) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def collect_files(paths: list[str]) -> list[Path]:
    if paths:
        return [p for p in map(Path, paths) if p.is_file() and is_python_file(p)]
    files: list[Path] = []
    for path in Path(".").rglob("*"):
        if not path.is_file():
            continue
        if any((part in IGNORED_DIRS for part in path.parts)):
            continue
        if not is_python_file(path):
            continue
        files.append(path)
    return files


def process_files(files: Iterable[Path], args: Namespace) -> list[tuple[Path, str]]:
    errors: list[tuple[Path, str]] = []
    cache = load_cache()
    updated_cache = cache.copy()

    def task(file: Path) -> None:
        current_hash = sha256(file)
        cached_hash = cache.get(str(file))
        if cached_hash == current_hash:
            return
        format_file(
            file,
            use_black=args.black,
            use_autopep=args.autopep,
            use_isort=args.isort,
            remove_unused=args.remove_all_unused_imports,
        )
        updated_cache[str(file)] = sha256(file)

    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(task, f): f for f in files}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Formatting", unit="file"):
            file = futures[future]
            try:
                future.result()
            except Exception as e:
                errors.append((file, str(e)))
    save_cache(updated_cache)
    return errors


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fast Python formatter (in-place)")
    p.add_argument("files", nargs="*", help="Files to format (optional)")
    p.add_argument("-b", "--black", action="store_true", help="Use black")
    p.add_argument("-a", "--autopep", action="store_true", help="Use autopep8")
    p.add_argument("-i", "--isort", action="store_true", help="Sort imports first")
    p.add_argument("-r", "--remove-all-unused-imports", action="store_true", help="Remove unused imports via autoflake")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    files = collect_files(args.files)
    if not files:
        print("No Python files detected.")
        return
    errors = process_files(files, args)
    if errors:
        print("\nErrors:")
        for file, err in errors:
            print(f"- {file}: {err}")
    else:
        print("Done. No errors.")


if __name__ == "__main__":
    main()
