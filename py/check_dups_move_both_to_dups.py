import re
import sys
from collections import defaultdict
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python check_dups.py <const_file.py>")
        sys.exit(1)
    src_path = Path(sys.argv[1])
    if not src_path.exists():
        print(f"File not found: {src_path}")
        sys.exit(1)
    dup_path = src_path.parent / "dups.py"
    assign_re = re.compile("^\\s*([A-Z_][A-Z0-9_]*)\\s*=")
    lines = src_path.read_text().splitlines(keepends=True)
    decls = defaultdict(list)
    for i, line in enumerate(lines):
        m = assign_re.match(line)
        if m:
            name = m.group(1)
            decls[name].append(i)
    duplicate_names = {k for k, v in decls.items() if len(v) > 1}
    if not duplicate_names:
        print("No duplicate declarations found.")
        return
    kept_lines = []
    dup_lines = []
    for i, line in enumerate(lines):
        m = assign_re.match(line)
        if m and m.group(1) in duplicate_names:
            dup_lines.append(line)
        else:
            kept_lines.append(line)
    src_path.write_text("".join(kept_lines))
    with dup_path.open("a") as f:
        f.write(f"\n# Duplicates from {src_path.name}\n")
        f.writelines(dup_lines)
    print(f"Moved {len(dup_lines)} duplicate declarations to {dup_path}")
    print(f"Updated {src_path} in place")


if __name__ == "__main__":
    main()
