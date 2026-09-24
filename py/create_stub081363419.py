from __future__ import annotations

import sys
from pathlib import Path
from dh import mpf3, get_files
from mypy.stubgen import generate_stubs


def process_file(path) -> None:
    path = Path(path)
    print(f"processing {path.name}")

    stubfile = path.with_suffix(".pyi")
    if stubfile.exists():
        print(f"[SKIP] {path.name} (stub already exists)")
        return

    try:
        generate_stubs([str(path)], output_dir=str(path.parent), verbose=True, pyversion=sys.version_info[:2])
        print(f"[OK] {path.name}")
    except Exception as e:
        print(f"[ERROR] {path.name}: {e}")


def main() -> None:
    cwd = Path.cwd()
    args = sys.argv[1:]

    files = [Path(p) for p in args] if args else get_files(cwd, ext=[".py"])
    if len(files) == 1:
        process_file(files[0])
        sys.exit(0)

    mpf3(process_file, files)

    stubless = []
    for f in files:
        stubpath = f.with_suffix(".pyi")
        if not stubpath.exists():
            stubless.append(f)

    if stubless:
        print("\nFiles without generated stubs:")
        for k in stubless:
            print(f" - {k.name}")


if __name__ == "__main__":
    sys.exit(main())
