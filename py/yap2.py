from __future__ import annotations
from argparse import Namespace
import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import autoflake
import autopep8
import black
import isort
from yapf.yapflib import yapf_api

IGNORED_DIRS = {".git", "dist", "build", "__pycache__", ".venv"}
CACHE_FILE = Path(".pyformat.cache")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def is_python_file(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    if path.suffix in {".pyi", ".pyx"}:
        return True
    try:
        with path.open("rb") as f:
            line = f.readline(100)
            if line.startswith(b"#!") and b"python" in line.lower():
                return True
    except Exception:
        pass
    return False


def format_file_content(
    file: Path, *, use_black: bool, use_autopep: bool, use_isort: bool, remove_unused: bool
) -> None:
    original_code = file.read_text(encoding="utf-8")
    code = original_code
    if remove_unused:
        code = autoflake.fix_code(
            code, remove_all_unused_imports=True, remove_unused_variables=True, expand_star_imports=True
        )
    if use_isort:
        code = isort.code(code)
    if use_black:
        try:
            code = black.format_str(code, mode=black.Mode())
        except black.NothingChanged:
            pass
    elif use_autopep:
        code = autopep8.fix_code(code, options={"aggressive": 2})
    else:
        code, _ = yapf_api.FormatCode(code)
    if code != original_code:
        file.write_text(code, encoding="utf-8")


def load_cache() -> dict[str, str]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def process_files(files: list[Path], args: Namespace) -> list[tuple[Path, str]]:
    errors: list[tuple[Path, str]] = []
    cache = load_cache()
    updated_cache = cache.copy()

    def task(file: Path) -> tuple[str, str] | None:
        curr_hash = sha256(file)
        if cache.get(str(file)) == curr_hash:
            return None
        try:
            format_file_content(
                file,
                use_black=args.black,
                use_autopep=args.autopep,
                use_isort=args.isort,
                remove_unused=args.remove_all_unused_imports,
            )
            return (str(file), sha256(file))
        except Exception as e:
            raise Exception(f"{file.name}: {str(e)}")

    print(f"Checking {len(files)} files...")
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_file = {executor.submit(task, f): f for f in files}
        for future in as_completed(future_to_file):
            file = future_to_file[future]
            try:
                result = future.result()
                if result:
                    path_str, new_hash = result
                    updated_cache[path_str] = new_hash
            except Exception as e:
                errors.append((file, str(e)))
    CACHE_FILE.write_text(json.dumps(updated_cache, indent=2))
    return errors


def collect_files(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p) for p in paths if Path(p).is_file() and is_python_file(Path(p))]
    found = []
    for path in Path(".").rglob("*"):
        if path.is_file() and (not any((p in IGNORED_DIRS for p in path.parts))):
            if is_python_file(path):
                found.append(path)
    return found


def main() -> None:
    p = argparse.ArgumentParser(description="Fast Python API-based formatter")
    p.add_argument("files", nargs="*", help="Specific files to format")
    p.add_argument("-b", "--black", action="store_true", help="Use black")
    p.add_argument("-a", "--autopep", action="store_true", help="Use autopep8")
    p.add_argument("-i", "--isort", action="store_true", help="Sort imports")
    p.add_argument("-r", "--remove-all-unused-imports", action="store_true", help="Remove unused imports")
    p.add_argument("-t", "--time", action="store_true", help="Show execution time")
    args = p.parse_args()
    start_time = time.perf_counter()
    files = collect_files(args.files)
    if not files:
        print("No Python files detected.")
        return
    errors = process_files(files, args)
    if errors:
        print("\nErrors encountered:")
        for file, err in errors:
            print(f"  - {file}: {err}")
    end_time = time.perf_counter()
    if args.time:
        print(f"\nTotal Runtime: {end_time - start_time:.4f} seconds")
    print("Done.")


if __name__ == "__main__":
    main()
