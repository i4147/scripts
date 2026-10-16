import contextlib
import subprocess
from multiprocessing import Pool, cpu_count
from pathlib import Path

EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
}


def should_skip(path: Path) -> bool:
    condition1 = True if any(part in EXCLUDE_DIRS for part in path.parts) else False
    condition2 = True if not gsz(path) else False
    condition3 = True if path.is_symlink() else False
    condition4 = True if path.is_file and path.stem.startswith(".") else False
    return condition1 or condition2 or condition3 or condition4


def minify_with_jq(
    path: Path,
) -> tuple[str, bool, str | None]:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        result = subprocess.run(
            ["jq", "-c", ".", str(path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return (
                str(path),
                False,
                result.stderr.strip(),
            )
        minified = result.stdout.strip()
        original = path.read_text(encoding="utf-8").strip()
        if original == minified:
            return str(path), False, None
        tmp_path.write_text(minified, encoding="utf-8")
        Path(tmp_path).replace(path)
        return str(path), True, None
    except Exception as e:
        return str(path), False, str(e)
    finally:
        if tmp_path.exists():
            with contextlib.suppress(Exception):
                tmp_path.unlink()


def collect_json_files(root: Path):
    for path in root.rglob("*.json"):
        if path.is_file() and not should_skip(path):
            yield path


def main() -> None:
    root = Path.cwd()
    files = list(collect_json_files(root))
    if not files:
        print("No JSON files found.")
        return
    workers = min(cpu_count(), len(files))
    print(f"Processing {len(files)} files using {workers} workers...\n")
    modified = 0
    skipped = 0
    errors = 0
    with Pool(processes=workers) as pool:
        for (
            filepath,
            changed,
            err,
        ) in pool.imap_unordered(minify_with_jq, files):
            if err:
                print(f"[ERROR] {filepath} -> {err}")
                errors += 1
            elif changed:
                print(f"[OK] {filepath}")
                modified += 1
            else:
                skipped += 1
    print("\n--- Summary ---")
    print(f"Total files: {len(files)}")
    print(f"Modified   : {modified}")
    print(f"Unchanged  : {skipped}")
    print(f"Errors     : {errors}")


if __name__ == "__main__":
    main()
