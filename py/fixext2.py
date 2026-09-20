import argparse
import os
import pathlib
import magic

MIME_TO_EXT = {
    "text/html": "html",
    "application/json": "json",
    "application/javascript": "js",
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/zip": "zip",
    "application/gzip": "gz",
    "application/x-tar": "tar",
    "text/xml": "xml",
}


def detect_text_based_extension(text: str):
    text = text.strip()
    if text.startswith("#!") and "python" in text:
        return "py"
    if any((tok in text for tok in ("def ", "class ", "import ", "from ", "__main__"))):
        return "py"
    if text.startswith("#!") and any((sh in text for sh in ("sh", "bash"))):
        return "sh"
    if text.startswith(("# ", "## ")) or "---" in text:
        return "md"
    if text.startswith("---") or (": " in text and "\n" in text):
        return "yaml"
    if "=" in text and "[" in text and ("]" in text):
        return "toml"
    if text.startswith("[") and "]" in text:
        return "ini"
    low = text.lower()
    if any((low.startswith(cmd) for cmd in ("select ", "insert ", "update ", "delete ", "create "))):
        return "sql"
    if "{" in text and "}" in text and (":" in text):
        return "css"
    if "," in text and "\n" in text:
        return "csv"
    if text.startswith("<?xml"):
        return "xml"
    return None


def detect_extension(path, mime_type: str, force_plain_to=None):
    if mime_type in MIME_TO_EXT:
        return MIME_TO_EXT[mime_type]
    if mime_type == "text/plain":
        if force_plain_to:
            return force_plain_to
        try:
            with pathlib.Path(path).open(encoding="utf-8", errors="ignore") as f:
                sample = f.read(4096)
            guessed = detect_text_based_extension(sample)
            if guessed:
                return guessed
        except Exception:
            pass
    return None


def safe_rename(src, dst_path: str):
    if not pathlib.Path(dst_path).exists():
        pathlib.Path(src).rename(dst_path)
        return dst_path
    base, ext = os.path.splitext(dst_path)
    counter = 1
    while True:
        new_path = f"{base} ({counter}){ext}"
        if not pathlib.Path(new_path).exists():
            pathlib.Path(src).rename(new_path)
            return new_path
        counter += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Recursively correct file extensions based on content")
    parser.add_argument(
        "--only", nargs="+", metavar="EXT", help="Only rename when detected extension is in this list (e.g. .html .py)"
    )
    parser.add_argument(
        "--skip", nargs="+", metavar="EXT", help="Skip files whose current extension is in this list (e.g. .log .bak)"
    )
    parser.add_argument("--force", metavar="MIME=EXT", help="Force mapping for given MIME (e.g. plain=txt)")
    parser.add_argument(
        "--exclude-dirs", nargs="+", metavar="DIR", help="Do not descend into these directories (names only)"
    )
    parser.add_argument(
        "--override", nargs="+", metavar="FROM=TO", help="Override extension mapping (e.g. htm=html jpeg=jpg)"
    )
    parser.add_argument("--path", default=".", help="Root directory to scan (default: current dir)")
    args = parser.parse_args()
    only_ext = {ext.lstrip(".").lower() for ext in args.only} if args.only else None
    skip_ext = {ext.lstrip(".").lower() for ext in args.skip} if args.skip else set()
    exclude_dirs = set(args.exclude_dirs) if args.exclude_dirs else set()
    force_plain_to = None
    if args.force:
        mime, ext = args.force.split("=", 1)
        mime = mime.strip().lower()
        ext = ext.strip().lstrip(".").lower()
        if mime == "plain":
            force_plain_to = ext
        else:
            print(f"Warning: forcing MIME '{mime}' is not supported; ignoring")
    overrides = {}
    if args.override:
        for ov in args.override:
            frm, to = ov.split("=", 1)
            overrides[frm.lstrip(".").lower()] = to.lstrip(".").lower()
    mime = magic.Magic(mime=True)
    for dirpath, dirnames, filenames in os.walk(args.path):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for name in filenames:
            full = os.path.join(dirpath, name)
            if pathlib.Path(full).is_symlink():
                continue
            parts = name.rsplit(".", 1)
            current_ext = parts[1].lower() if len(parts) == 2 else ""
            if current_ext in skip_ext:
                continue
            try:
                mime_type = mime.from_file(full)
            except Exception as e:
                print(f"Skipping unreadable: {full}. Error: {e}")
                continue
            new_ext = detect_extension(full, mime_type, force_plain_to=force_plain_to)
            if not new_ext:
                continue
            new_ext = overrides.get(new_ext, new_ext)
            if only_ext is not None and new_ext not in only_ext:
                continue
            if current_ext == new_ext:
                continue
            base = parts[0] if len(parts) == 2 else name
            new_name = f"{base}.{new_ext}"
            dst = os.path.join(dirpath, new_name)
            print(f"Renaming: {full} → {dst}")
            final = safe_rename(full, dst)
            if final != dst:
                print(f" ⚠ Collision — saved as: {final}")


if __name__ == "__main__":
    main()
