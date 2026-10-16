from __future__ import annotations

import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from dh import fsz


@dataclass
class FileStats:
    path: Path
    lines_before: int
    lines_after: int
    size_before: int
    size_after: int
    removed_lines: int
    removed_refs: int


RST_IMAGE_PATTERNS = [
    re.compile(r"^\s*\.\.\s+image::\s+https?://[^\s]+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*\.\.\s+figure::\s+https?://[^\s]+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*\.\.\s+\|.*\|\s+image::\s+https?://[^\s]+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*\.\.\s+image::\s+(?!https?://)[^\s]+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*\.\.\s+figure::\s+(?!https?://)[^\s]+", re.IGNORECASE | re.MULTILINE),
    re.compile(
        r"^\s*\.\.\s+\|.*\|\s+replace::\s+https?://[^\s]+\.(?:png|jpg|jpeg|gif|svg|ico)(?:\?[^\s]*)?",
        re.IGNORECASE | re.MULTILINE,
    ),
]
MD_IMAGE_PATTERNS = [
    re.compile(r"^\[!\[.*?\]\(https?://[^\)]+\)\]\(https?://[^\)]+\)", re.MULTILINE),
    re.compile(r"!\[.*?\]\(https?://[^\)]+\)", re.MULTILINE),
    re.compile(r"!\[.*?\]\((?!https?://)[^\)]+\)", re.MULTILINE),
    re.compile(r'<img[^>]+src\s*=\s*["\'][^"\']+["\'][^>]*>', re.IGNORECASE),
    re.compile(
        r"^\[.*?\]:\s+https?://[^\s]+\.(?:png|jpg|jpeg|gif|svg|ico)(?:\?[^\s]*)?",
        re.IGNORECASE | re.MULTILINE,
    ),
]
BADGE_DOMAINS = [
    "shields.io",
    "img.shields.io",
    "badge.fury.io",
    "badges.gitter.im",
    "travis-ci.org",
    "travis-ci.com",
    "circleci.com",
    "codecov.io",
    "coveralls.io",
    "readthedocs.org",
    "readthedocs.io",
    "github.com/.*/workflows/.*badge",
    "ci.appveyor.com",
    "dev.azure.com",
    "scrutinizer-ci.com",
    "packagist.org",
    "david-dm.org",
    "snyk.io",
    "badges.greenkeeper.io",
    "api.codacy.com",
    "goreportcard.com",
    "opencollective.com",
    "buymeacoffee.com",
    "patreon.com",
]


def has_badge_domain(line: str) -> bool:
    return any(re.search(domain, line, re.IGNORECASE) for domain in BADGE_DOMAINS)


def is_image_extension_url(line: str) -> bool:
    image_extensions = r"\.(?:png|jpg|jpeg|gif|svg|ico|webp|bmp)(?:\?|#|$|\))"
    return bool(re.search(image_extensions, line, re.IGNORECASE))


def remove_image_lines_rst(content: str) -> tuple[str, int]:
    lines = content.split("\n")
    new_lines = []
    removed_count = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        should_remove = False
        for pattern in RST_IMAGE_PATTERNS:
            if pattern.match(line):
                should_remove = True
                break
        if (
            not should_remove
            and ("image::" in line or "figure::" in line or "replace::" in line)
            and (has_badge_domain(line) or is_image_extension_url(line))
        ):
            should_remove = True
        if should_remove:
            removed_count += 1
            if i + 1 < len(lines) and lines[i + 1].strip().startswith(":"):
                i += 1
        else:
            new_lines.append(line)
        i += 1
    return "\n".join(new_lines), removed_count


def remove_image_lines_md(content: str) -> tuple[str, int]:
    lines = content.split("\n")
    new_lines = []
    removed_count = 0
    for line in lines:
        original_line = line
        should_remove = False
        linked_badge_pattern = re.compile(r"^\[!\[.*?\]\(https?://[^\)]+\)\]\(https?://[^\)]+\)")
        if linked_badge_pattern.match(line):
            should_remove = True
        if not should_remove:
            for pattern in MD_IMAGE_PATTERNS:
                if pattern.search(line):
                    cleaned = pattern.sub("", line).strip()
                    if not cleaned or cleaned == line:
                        if has_badge_domain(line) or is_image_extension_url(line):
                            should_remove = True
                        break
                    else:
                        line = cleaned
                        break
        if not should_remove:
            md_link_pattern = re.compile(r"\[([^\]]*)\]\(([^\)]+)\)")
            matches = md_link_pattern.findall(line)
            for _text, url in matches:
                if has_badge_domain(url) or is_image_extension_url(url):
                    if "!" in line or "badge" in url.lower() or "shield" in url.lower():
                        should_remove = True
                        break
        if should_remove:
            removed_count += 1
        else:
            if line.strip() or (new_lines and new_lines[-1].strip()) or not new_lines:
                new_lines.append(line)
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()
    result = "\n".join(new_lines)
    if content.endswith("\n"):
        result += "\n"
    return result, removed_count


def process_file(file_path: Path) -> FileStats | None:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return None
        lines_before = content.count("\n") + 1
        size_before = len(content.encode("utf-8"))
        suffix = file_path.suffix.lower()
        if suffix == ".rst":
            new_content, removed_refs = remove_image_lines_rst(content)
        elif suffix == ".md":
            new_content, removed_refs = remove_image_lines_md(content)
        else:
            return None
        if removed_refs > 0:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            lines_after = new_content.count("\n") + 1
            size_after = len(new_content.encode("utf-8"))
            return FileStats(
                path=file_path,
                lines_before=lines_before,
                lines_after=lines_after,
                size_before=size_before,
                size_after=size_after,
                removed_lines=lines_before - lines_after,
                removed_refs=removed_refs,
            )
    except Exception as e:
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return None


def collect_files(directories: list[Path]) -> list[Path]:
    files = []
    for directory in directories:
        if not directory.exists():
            print(
                f"Warning: Directory '{directory}' does not exist, skipping...",
                file=sys.stderr,
            )
            continue
        if not directory.is_dir():
            print(
                f"Warning: '{directory}' is not a directory, skipping...",
                file=sys.stderr,
            )
            continue
        for ext in ["*.rst", "*.md"]:
            files.extend(directory.rglob(ext))
    return sorted(set(files))


def print_stats(all_stats: list[FileStats], base_path: Path):
    if not all_stats:
        print("\n✨ No image references found to remove!")
        return
    print("\n" + "=" * 40)
    print("📊 IMAGE REFERENCE REMOVAL REPORT")
    print("-" * 40)
    total_lines_before = 0
    total_lines_after = 0
    total_size_before = 0
    total_size_after = 0
    total_removed_refs = 0
    for stats in all_stats:
        rel_path = stats.path.relative_to(base_path)
        size_change = stats.size_before - stats.size_after
        change_symbol = "↓" if size_change > 0 else "→"
        print(f"\n📄 {rel_path}")
        print(f"   ├─ Image references removed: {stats.removed_refs}")
        print(f"   ├─ Lines: {stats.lines_before} → {stats.lines_after} ({stats.removed_lines:+d})")
        print(
            f"   ├─ Size: {fsz(stats.size_before)} → {fsz(stats.size_after)} ({change_symbol} {fsz(abs(size_change))})"
        )
        if stats.size_before > 0:
            print(f"   └─ Reduction: {(size_change / stats.size_before * 40):.1f}%")
        total_lines_before += stats.lines_before
        total_lines_after += stats.lines_after
        total_size_before += stats.size_before
        total_size_after += stats.size_after
        total_removed_refs += stats.removed_refs
    print("\n" + "=" * 40)
    print("📈 SUMMARY")
    print("-" * 40)
    print(f"Files modified: {len(all_stats)}")
    print(f"Total image references removed: {total_removed_refs}")
    print(f"Total lines: {total_lines_before} → {total_lines_after} ({total_lines_before - total_lines_after:+d})")
    print(
        f"Total size: {fsz(total_size_before)} → {fsz(total_size_after)} "
        f"({fsz(total_size_before - total_size_after)} saved)"
    )
    if total_size_before > 0:
        print(f"Overall reduction: {((total_size_before - total_size_after) / total_size_before * 40):.1f}%")
    print("-" * 40)


def main():
    if len(sys.argv) > 1:
        directories = [Path(arg) for arg in sys.argv[1:]]
    else:
        directories = [Path.cwd()]
    print("🔍 Scanning for .rst and .md files...")
    files = collect_files(directories)
    print(f"Found {len(files)} files to process")
    if not files:
        print("No .rst or .md files found in the specified directories.")
        return
    print("⚡ Processing files in parallel...")
    stats_list = []
    with ProcessPoolExecutor() as executor:
        future_to_file = {executor.submit(process_file, file): file for file in files}
        completed = 0
        for future in as_completed(future_to_file):
            completed += 1
            file = future_to_file[future]
            try:
                stats = future.result()
                if stats:
                    stats_list.append(stats)
                if completed % 10 == 0 or completed == len(files):
                    print(
                        f"  Progress: {completed}/{len(files)} files processed",
                        end="\r",
                    )
            except Exception as e:
                print(f"\nError processing {file}: {e}", file=sys.stderr)
    print(f"\n✅ Processed {len(files)} files")
    base_path = Path.cwd()
    stats_list.sort(key=lambda x: str(x.path))
    print_stats(stats_list, base_path)


if __name__ == "__main__":
    raise SystemExit(main())
