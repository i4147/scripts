import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

LOCAL_FONT_BASE = Path("/sdcard/_static/fonts")
FONT_EXTS = {
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
}
IMG_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
}
IMPORT_RE = re.compile(
    r"@import\s+url\([^)]+fonts\.googleapis[^)]+\);?",
    re.IGNORECASE,
)
FAMILY_RULES = {
    "roboto": "roboto",
    "lato": "lato",
    "opensans": "opensans",
    "open-sans": "opensans",
    "fontawesome": "fa",
    "fa-": "fa",
}
URL_RE = re.compile(
    r'url\((["\']?)(https?://[^)]+?\.(?:woff2?|ttf|otf|eot))\1\)',
    re.IGNORECASE,
)


def find_css(paths, recursive: bool = False):
    seen = set()
    result = []
    for p in paths:
        p = Path(p)
        if p.is_file() and p.suffix.lower() == ".css":
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                result.append(rp)
        elif p.is_dir():
            pattern = "**/*.css" if recursive else "*.css"
            for f in sorted(p.glob(pattern)):
                rp = f.resolve()
                if rp not in seen:
                    seen.add(rp)
                    result.append(rp)
        else:
            print(
                f"Skipping invalid path: {p}",
                file=sys.stderr,
            )
    return result


def read_css(files):
    charset_line = None
    chunks = []

    def localize_font_url(match) -> str:
        url = match.group(2)
        filename = url.split("/")[-1]
        return f'url("{LOCAL_FONT_BASE}/{filename}")'

    for file in files:
        text = file.read_text(errors="ignore")
        text = IMPORT_RE.sub("", text)
        text = URL_RE.sub(localize_font_url, text)
        lines = text.splitlines()
        cleaned = []
        for line in lines:
            stripped = line.strip().lower()
            if stripped.startswith("@charset"):
                if charset_line is None:
                    charset_line = line.strip()
                continue
            cleaned.append(line)
        chunks.append((file, "\n".join(cleaned).strip()))
    return charset_line, chunks


def atomic_write(path, content: str) -> None:
    path = Path(path)
    tmp = tempfile.NamedTemporaryFile(
        delete=False,
        dir=str(path.parent),
        mode="w",
        encoding="utf-8",
    )
    try:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        Path(tmp.name).replace(path)
    finally:
        try:
            Path(tmp.name).unlink()
        except OSError:
            pass


def join_css(files, output) -> None:
    charset, chunks = read_css(files)
    parts = []
    if charset:
        parts.append(charset + "\n")
    for file, content in chunks:
        parts.append(f"\n/* ===== {file.name} ===== */\n{content}\n")
    final_css = "\n".join(parts).strip() + "\n"
    atomic_write(output, final_css)


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely join CSS files.")
    parser.add_argument(
        "paths",
        default=".",
        nargs="*",
        help="CSS files or directories",
    )
    parser.add_argument("-o", "--output", default="merged.css")
    parser.add_argument(
        "-r",
        "--recursive",
        default=True,
        action="store_true",
    )
    args = parser.parse_args()
    files = find_css(args.paths, args.recursive)
    if not files:
        print("No CSS files found.", file=sys.stderr)
        sys.exit(1)
    join_css(files, args.output)
    print(f"Joined {len(files)} files -> {args.output}")


if __name__ == "__main__":
    main()
