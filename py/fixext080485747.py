from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dh import MIME2EXT, SHEBANG_MAP, colored, cprint, is_binary, runcmd, unique_path

SKIP_DIRS = {".git", "__pycache__"}

SKIP_EXTS = {".css", ".js"}


def fix_by_shebang(path: Path) -> str | None:
    if is_binary(path):
        return None
    try:
        with open(path, "rb") as f:
            first_line = f.readline(256)
        if not first_line.startswith(b"#!"):
            return None
        shebang = first_line.decode("utf-8", errors="replace").strip()
        for interpreter, ext in SHEBANG_MAP.items():
            if interpreter in shebang:
                return ext
        return None
    except Exception:
        return None


def get_file_mime(path: Path) -> str | None:
    result = runcmd(["file", "--brief", "--mime-type", str(path)])
    if result["exit_code"] != 0:
        return None
    mime = result["stdout"].strip()
    if not mime:
        return None
    return mime


def safe_rename(old: Path, new: Path) -> bool:
    try:
        new = unique_path(new)
        old.rename(new)
        return True
    except Exception:
        return False


def process_directory(directory: Path, confirm: bool = False) -> list[dict]:
    mismatches: list[dict] = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for file in files:
            file_path = Path(root) / file
            if not file_path.is_file() or file_path.is_symlink():
                continue
            if file_path.stat().st_size == 0:
                continue
            ext = file_path.suffix.lower()
            if ext in SKIP_EXTS:
                continue
            shebang_ext = fix_by_shebang(file_path)
            if shebang_ext:
                current_ext = file_path.suffix.lower()
                if current_ext != shebang_ext:
                    new_name = file_path.with_suffix(shebang_ext).name
                    new_path = file_path.with_name(new_name)
                    mismatches.append(
                        {
                            "path": file_path,
                            "mime": "shebang",
                            "current_ext": current_ext or "(none)",
                            "expected_ext": shebang_ext,
                            "new_path": new_path,
                        }
                    )
                continue
            mime = get_file_mime(file_path)
            if not mime:
                continue
            if mime == "text/plain":
                continue
            expected_exts = MIME2EXT.get(mime, [])
            if not expected_exts:
                continue
            expected_ext = expected_exts[0]
            current_ext = file_path.suffix.lower()
            if current_ext == expected_ext:
                continue
            if current_ext in expected_exts:
                continue
            if current_ext:
                new_name = file_path.stem + expected_ext
            else:
                new_name = file_path.name + expected_ext
            new_path = file_path.with_name(new_name)
            mismatches.append(
                {
                    "path": file_path,
                    "mime": mime,
                    "current_ext": current_ext or "(none)",
                    "expected_ext": expected_ext,
                    "new_path": new_path,
                }
            )
    return mismatches


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix file extension mismatches by analyzing file content.")
    parser.add_argument("-y", action="store_true", help="Enable confirmation mode")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        cprint(f"Error: {directory} is not a valid directory", color="red", attrs=["bold"])
        sys.exit(1)
    mismatches = process_directory(directory, confirm=args.y)
    if not mismatches:
        cprint("No mismatches found.", color="green", attrs=["bold"])
        sys.exit(0)
    cprint(
        f"\nFound {len(mismatches)} mismatched file(s):\n",
        color="yellow",
        attrs=["bold"],
    )
    for item in mismatches:
        orig = colored(str(item["path"]), color="red", attrs=["bold"])
        mime_info = colored(f"mime={item['mime']}", color="cyan")
        expected = colored(f"expected ext ={item['expected_ext']}", color="green")
        new_name = colored(item["new_path"].name, color="green", attrs=["bold"])
        print(f"{orig}")
        print(f"  {mime_info}")
        print(f"  {expected}")
        print(f"  new name = {new_name}")
        if args.y:
            response = input(f"  {item['path'].name} -> {item['new_path'].name} ? [y/N] ").strip().lower()
            if response != "y":
                print("  Skipped.")
                continue
        if safe_rename(item["path"], item["new_path"]):
            cprint(f"  Renamed to {item['new_path'].name}", color="green")
        else:
            cprint("  Failed to rename", color="red", attrs=["bold"])
        print()
    cprint("Done.", color="green", attrs=["bold"])


if __name__ == "__main__":
    main()
