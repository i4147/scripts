import shutil
import subprocess
from pathlib import Path
from dh import mpf, unique_path

EXTENSIONS = {".js", ".css", ".html", ".json", ".mjs", ".cjs", ".ts", ".jsx", ".tsx"}
EXCLUDE_PATTERNS = {".py", ".ipynb"}


def should_format(file_path: Path) -> bool:
    return file_path.suffix in EXTENSIONS and not any(file_path.name.endswith(p) for p in EXCLUDE_PATTERNS)


def get_files_to_format(cwd: str = ".") -> list[Path]:
    return [p for p in Path(cwd).resolve().rglob("*") if p.is_file() and "error" not in p.parts and should_format(p)]


def format_file(file_path: Path) -> tuple[Path, bool, str | None]:
    try:
        result = subprocess.run(
            ["prettier", "--write", str(file_path)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            return file_path, True, None
        return file_path, False, result.stderr or "Unknown error"
    except Exception as e:
        return file_path, False, str(e)


def main() -> None:
    cwd = Path.cwd()
    files = get_files_to_format(cwd)
    if not files:
        print("ℹ️  No files found to format")
        return
    print(f"📁 Scanning: {cwd} | 📝 Found {len(files)} files")
    success_count = 0
    error_count = 0
    results = mpf(format_file, files)
    for result in results:
        path, success, error_msg = result
        if success:
            print(f"  ✅ Formatted: {path.name}")
            success_count += 1
        else:
            print(f"  ❌ Error: {path.name} -> {error_msg}")
            error_dir = path.parent / "error"
            error_dir.mkdir(exist_ok=True)
            dest = unique_path(error_dir / path.name)
            shutil.move(str(path), str(dest))
            error_count += 1
    print(f"\n✅ Success: {success_count} | ❌ Errors: {error_count}")


if __name__ == "__main__":
    main()
