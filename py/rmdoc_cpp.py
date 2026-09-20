from __future__ import annotations

import re
import sys
from pathlib import Path
from dh import fsz


class RegexCommentRemover:
    def __init__(self) -> None:
        self.pattern = re.compile(
            r"//.*?$|/\*.*?\*/|'(?:\.|[^'])*'|\"(?:\.|[^\"])*\"",
            re.DOTALL | re.MULTILINE,
        )

    def remove_comments(self, source: str) -> tuple[str, int]:
        def replacer(match):
            s = match.group(0)
            if s.startswith("/"):
                return " " if "\n" not in s else "\n" * s.count("\n")
            return s

        result = re.sub(self.pattern, replacer, source)
        comment_count = source.count("//") + source.count("/*")
        result_count = result.count("//") + result.count("/*")
        removed = comment_count - result_count
        return result, removed


def process_file(file_path: Path, remover: RegexCommentRemover):
    Path(path)
    try:
        code = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"[ERROR] {file_path.name} read: {e}")
        return "error", file_path, 0
    try:
        result, comments = remover.remove_comments(code)
    except Exception as e:
        print(f"[ERROR] {file_path.name} processing: {e}")
        import traceback

        traceback.print_exc()
        return "error", file_path, 0
    if result != code:
        try:
            Path(file_path).write_text(result, encoding="utf-8")
            print(f"[OK] {file_path.name}: ~{comments} comment markers removed")
            return "changed", file_path, comments
        except Exception as e:
            print(f"[ERROR] {file_path.name} write: {e}")
            return "error", file_path, comments
    else:
        print(f"[NO CHANGE] {file_path.name}")
        return "nochange", file_path, 0


if __name__ == "__main__":
    dir_path = Path.cwd()
    files = [
        p
        for p in dir_path.rglob("*")
        if p.suffix in {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx", ".C", ".H"} and p.is_file()
    ]
    if not files:
        print("No C/C++ files found")
        sys.exit(0)
    print(f"Found {len(files)} C/C++ files")
    before = sum(f.stat().st_size for f in files)
    remover = RegexCommentRemover()
    results = []
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] Processing {path.name}...")
        result = process_file(path, remover)
        results.append(result)
    after = sum(f.stat().st_size for f in files if f.exists())
    changed = sum(1 for r in results if r[0] == "changed")
    errors = [r for r in results if r[0] == "error"]
    nochg = sum(1 for r in results if r[0] == "nochange")
    total_comments = sum(r[2] for r in results if r[0] == "changed")

    print(f"\n{'=' * 42}")
    print(f"Files: {len(files)} | Changed: {changed} | Unchanged: {nochg} | Errors: {len(errors)}")
    print(f"Total comment markers removed: ~{total_comments}")
    if errors:
        print("\nErrors in:")
        for _, fn, *_ in errors[:10]:
            print(f"  - {fn}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
    print(f"Size reduced: {fsz(before - after)}")
    print(f"{'=' * 42}")
