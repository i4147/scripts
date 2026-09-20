from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from re import sub
from subprocess import PIPE, run


def convert_info_file(info_path: Path) -> None:
    stem = info_path.name
    base_name = sub(r"\.info(-\d+)?$", "", stem)
    md_path = info_path.parent / f"{base_name}.md"
    if md_path.exists():
        index = 1
        while (info_path.parent / f"{base_name}_{index}.md").exists():
            index += 1
        md_path = info_path.parent / f"{base_name}_{index}.md"
    result = run(["info", str(info_path)], capture_output=True, text=True)
    if result.returncode == 0:
        md_path.write_text(result.stdout)
        info_path.unlink()


def main():
    cwd = Path.cwd()
    info_files = list(cwd.glob("*.info*"))
    with ThreadPoolExecutor(max_workers=4) as executor:
        executor.map(convert_info_file, info_files)


if __name__ == "__main__":
    raise SystemExit(main())
