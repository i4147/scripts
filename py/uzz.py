from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile


def get_package_name(wheel_filename: str) -> str:
    parts = wheel_filename.replace(".whl", "").split("-")
    for i, part in enumerate(parts):
        if part[0].isdigit():
            return "-".join(parts[:i])
    return parts[0]


def extract_wheel(wheel_path: Path) -> tuple[str, bool]:
    pkg_name = get_package_name(wheel_path.name)
    output_dir = wheel_path.parent / pkg_name
    output_dir.mkdir(exist_ok=True)
    try:
        with ZipFile(wheel_path) as whl:
            whl.extractall(output_dir)
        wheel_path.unlink()
        return wheel_path.name, True
    except Exception as e:
        return f"{wheel_path.name}: {e}", False


def main():
    wheels = list(Path.cwd().glob("*.whl"))
    if not wheels:
        print("No .whl files found")
        return
    with ThreadPoolExecutor() as executor:
        results = executor.map(extract_wheel, wheels)
    for name, success in results:
        status = "✓" if success else "✗"
        print(f"{status} {name}")


if __name__ == "__main__":
    raise SystemExit(main())
