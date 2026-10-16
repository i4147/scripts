import re
import sys
from dataclasses import dataclass
from multiprocessing.pool import Pool
from pathlib import Path
from dh import fsz
from loguru import logger

POOL_SIZE = 8
RST_IMAGE_PATTERNS = [
    re.compile(r"^\s*\.\.\s+image::\s+https?://[^\s]+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*\.\.\s+figure::\s+https?://[^\s]+", re.IGNORECASE | re.MULTILINE),
    re.compile(
        r"^\s*\.\.\s+\|.*\|\s+image::\s+https?://[^\s]+",
        re.IGNORECASE | re.MULTILINE,
    ),
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
_LINKED_BADGE_PATTERN = re.compile(r"^\[!\[.*?\]\(https?://[^\)]+\)\]\(https?://[^\)]+\)")
_MD_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\(([^\)]+)\)")


@dataclass
class FileStats:
    pass


def has_badge_domain(line):
    return any(re.search(domain, line, re.IGNORECASE) for domain in BADGE_DOMAINS)


def is_image_extension_url(line):
    image_extensions = r"\.(?:png|jpg|jpeg|gif|svg|ico|webp|bmp)(?:\?|#|$|\))"
    return bool(re.search(image_extensions, line, re.IGNORECASE))


def remove_image_lines_rst(content):
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


def remove_image_lines_md(content):
    lines = content.split("\n")
    new_lines = []
    removed_count = 0
    for raw_line in lines:
        line = raw_line
        should_remove = False
        if _LINKED_BADGE_PATTERN.match(line):
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
            matches = _MD_LINK_PATTERN.findall(line)
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


def process_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return None
        lines_before = content.count("\n") + 1
        size_before = len(content.encode("utf-8"))
        suffix = path.suffix.lower()
        if suffix == ".rst":
            new_content, removed_refs = remove_image_lines_rst(content)
        elif suffix == ".md":
            new_content, removed_refs = remove_image_lines_md(content)
        else:
            return None
        if removed_refs > 0:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            lines_after = new_content.count("\n") + 1
            size_after = len(new_content.encode("utf-8"))
            return FileStats(
                path=path,
                lines_before=lines_before,
                lines_after=lines_after,
                size_before=size_before,
                size_after=size_after,
                removed_lines=lines_before - lines_after,
                removed_refs=removed_refs,
            )
    except Exception as e:
        logger.error(f"Error processing {path}: {e}")
        return None
    return None


def collect_files(directories):
    files = []
    for directory in directories:
        if not directory.exists():
            logger.warning(f"Directory '{directory}' does not exist, skipping...")
            continue
        if not directory.is_dir():
            logger.warning(f"'{directory}' is not a directory, skipping...")
            continue
        for ext in ("*.rst", "*.md"):
            files.extend(directory.rglob(ext))
    return sorted(set(files))


def print_stats(all_stats, base_path):
    if not all_stats:
        print("✨ No image references found to remove!")
        return
    print("=" * 40)
    print("📊 IMAGE REFERENCE REMOVAL REPORT")
    print("-" * 40)
    total_lines_before = 0
    total_lines_after = 0
    total_size_before = 0
    total_size_after = 0
    total_removed_refs = 0
    for stats in all_stats:
        try:
            rel_path = stats.path.relative_to(base_path)
        except ValueError:
            rel_path = stats.path
        size_change = stats.size_before - stats.size_after
        change_symbol = "↓" if size_change > 0 else "→"
        print(f"📄 {rel_path}")
        print(f"   ├─ Image references removed: {stats.removed_refs}")
        print(f"   ├─ Lines: {stats.lines_before} → {stats.lines_after} ({stats.removed_lines:+d})")
        print(
            f"   ├─ Size: {fsz(stats.size_before)} → {fsz(stats.size_after)} ({change_symbol} {fsz(abs(size_change))})"
        )
        if stats.size_before > 0:
            print(f"   └─ Reduction: {(size_change / stats.size_before * 100):.1f}%")
        total_lines_before += stats.lines_before
        total_lines_after += stats.lines_after
        total_size_before += stats.size_before
        total_size_after += stats.size_after
        total_removed_refs += stats.removed_refs
    print("=" * 40)
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
        print(f"Overall reduction: {((total_size_before - total_size_after) / total_size_before * 100):.1f}%")
    print("-" * 40)


def main():
    argv = sys.argv[1:]
    directories = [Path(arg) for arg in argv] if argv else [Path.cwd()]
    print("🔍 Scanning for .rst and .md files...")
    files = collect_files(directories)
    print(f"Found {len(files)} files to process")
    if not files:
        print("No .rst or .md files found in the specified directories.")
        return 0
    print(f"⚡ Processing files in parallel with {POOL_SIZE} workers...")
    stats_list = []
    completed = 0
    total = len(files)
    with Pool(processes=POOL_SIZE) as pool:
        async_results = [(pool.apply_async(process_file, (file,)), file) for file in files]
        for result, file in async_results:
            completed += 1
            try:
                stats = result.get()
                if stats is not None:
                    stats_list.append(stats)
            except Exception as e:
                logger.error(f"Error processing {file}: {e}")
            if completed % 10 == 0 or completed == total:
                print(f"  Progress: {completed}/{total} files processed")
    print(f"✅ Processed {total} files")
    base_path = Path.cwd()
    stats_list.sort(key=lambda x: str(x.path))
    print_stats(stats_list, base_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
