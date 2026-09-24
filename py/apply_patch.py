from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional


DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)\s*$")
HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: (.*))?$")


def strip_prefix(path: str, strip: int) -> str:
    parts = path.split("/")
    return "/".join(parts[strip:]) if strip < len(parts) else path


def parse_patch(text: str):
    lines = text.splitlines(keepends=True)
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        m = DIFF_HEADER_RE.match(line)
        if not m:
            i += 1
            continue

        old_path, new_path = m.group(1), m.group(2)
        i += 1

        while i < n and not lines[i].startswith("@@"):
            if lines[i].startswith("diff --git "):
                break
            i += 1

        hunks = []
        while i < n and lines[i].startswith("@@"):
            hm = HUNK_HEADER_RE.match(lines[i])
            if not hm:
                raise ValueError(f"Bad hunk header: {lines[i]!r}")
            old_start = int(hm.group(1))
            old_count = int(hm.group(2)) if hm.group(2) is not None else 1
            new_start = int(hm.group(3))
            new_count = int(hm.group(4)) if hm.group(4) is not None else 1
            i += 1

            hunk_lines = []
            while i < n:
                hl = lines[i]
                if hl.startswith("@@") or hl.startswith("diff --git "):
                    break
                if hl.startswith("\\"):
                    i += 1
                    continue
                if hl and hl[0] in " +-":
                    hunk_lines.append(hl)
                    i += 1
                elif hl == "\n" or hl == "":
                    hunk_lines.append(" \n")
                    i += 1
                else:
                    break

            hunks.append(
                {
                    "old_start": old_start,
                    "old_count": old_count,
                    "new_start": new_start,
                    "new_count": new_count,
                    "lines": hunk_lines,
                }
            )

        yield old_path, new_path, hunks


def apply_hunk(file_lines: list[str], hunk: dict, fuzz: int = 0) -> Optional[list[str]]:
    old_start = hunk["old_start"]
    old_count = hunk["old_count"]
    hunk_lines = hunk["lines"]

    old_side = []
    for hl in hunk_lines:
        tag = hl[0]
        content = hl[1:]
        if tag in (" ", "-"):
            old_side.append(content)

    candidates = [old_start - 1]
    for offset in range(1, fuzz + 1):
        candidates.append(old_start - 1 - offset)
        candidates.append(old_start - 1 + offset)

    for pos in candidates:
        if pos < 0:
            continue
        if old_side == file_lines[pos : pos + len(old_side)]:
            new_side = []
            for hl in hunk_lines:
                tag = hl[0]
                content = hl[1:]
                if tag in (" ", "+"):
                    new_side.append(content)
            return file_lines[:pos] + new_side + file_lines[pos + len(old_side) :]

    return None


def apply_to_file(path: Path, hunks: list[dict], reverse: bool, fuzz: int, dry_run: bool) -> bool:
    original = path.read_text()
    file_lines = original.splitlines(keepends=True)

    if original and not original.endswith("\n"):
        pass

    all_hunks = list(reversed(hunks)) if reverse else hunks

    for hunk in all_hunks:
        result = apply_hunk(file_lines, hunk, fuzz=fuzz)
        if result is None:
            print(f"  ! hunk at line {hunk['old_start']} failed for {path}", file=sys.stderr)
            return False
        file_lines = result

    if not dry_run:
        path.write_text("".join(file_lines))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Manually apply a unified diff patch.")
    ap.add_argument("patchfile")
    ap.add_argument("-p", "--strip", type=int, default=1, help="strip N leading path components (default 1)")
    ap.add_argument("-R", "--reverse", action="store_true")
    ap.add_argument("--fuzz", type=int, default=0, help="allow hunk to apply N lines off target")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--skip-missing", action="store_true", default=True, help="skip files that don't exist (default: True)"
    )
    args = ap.parse_args()

    patch_text = Path(args.patchfile).read_text()
    any_applied = False

    for old_path, new_path, hunks in parse_patch(patch_text):
        target_rel = strip_prefix(new_path if not args.reverse else old_path, args.strip)
        target = Path(target_rel)

        if not target.exists():
            if args.skip_missing:
                print(f"skip (missing): {target}")
                continue
            print(f"error: {target} does not exist", file=sys.stderr)
            return 1

        print(f"apply: {target} ({len(hunks)} hunk(s))")
        ok = apply_to_file(target, hunks, args.reverse, args.fuzz, args.dry_run)
        if not ok:
            print(f"  -> FAILED {target}", file=sys.stderr)
            return 2
        any_applied = True

    return 0 if any_applied else 3


if __name__ == "__main__":
    raise SystemExit(main())
