import multiprocessing as mp
import os
import pathlib

EXCLUDE_DIRS = {".git", "__pycache__"}
EXCLUDED_EXT = {
    ".whl",
    ".zip",
    ".tar.gz",
    ".gz",
    ".tar.xz",
    ".7z",
}
PATTERNS = []


def init_worker(patterns) -> None:
    global PATTERNS
    PATTERNS = patterns


def is_binary(path) -> bool:
    try:
        with pathlib.Path(path).open("rb") as f:
            chunk = f.read(4096)
            if b"\0" in chunk:
                return True
    except:
        return True
    return False


def load_patterns_from_file(
    path: str = "/sdcard/all.txt",
) -> list[str]:
    if not pathlib.Path(path).exists():
        msg = f"{path} not found"
        raise FileNotFoundError(msg)
    content = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    raw_groups = [block.strip() for block in content.split("\n\n\n")]
    patterns = [g for g in raw_groups if g and len(g) >= 5]
    print(f"Filtered out {len(raw_groups) - len(patterns)} short patterns (<5 chars)")
    with pathlib.Path("/sdcard/all.txt").open("w", encoding="utf-8") as fo:
        for gg in list(set(patterns)):
            fo.write(gg)
            fo.write("\n\n\n")
    return list(set(patterns))


def process_file(path) -> str | None:
    if is_binary(path):
        return f"Skipping binary: {path}"
    try:
        data = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"ERROR reading {path}: {e}"
    new_data = data
    for p in PATTERNS:
        new_data = new_data.replace(p, "")
    if new_data != data:
        try:
            pathlib.Path(path).write_text(new_data, encoding="utf-8")
            return f"Cleaned: {path}"
        except Exception as e:
            return f"ERROR writing {path}: {e}"
    return None


def collect_files(root):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fname in filenames:
            if fname == "all.txt":
                continue
            if any(fname.endswith(ext) for ext in EXCLUDED_EXT):
                continue
            full = os.path.join(dirpath, fname)
            files.append(full)
    return files


def clean_dir_mp(root, patterns: list[str]) -> None:
    files = collect_files(root)
    print(f"Found {len(files)} candidate files")
    with mp.Pool(
        mp.cpu_count(),
        initializer=init_worker,
        initargs=(patterns,),
    ) as pool:
        for result in pool.imap_unordered(process_file, files):
            if result:
                print(result)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Remove strings from text files recursively (MP)")
    ap.add_argument(
        "--path",
        default=".",
        help="Directory to clean",
    )
    ap.add_argument(
        "--file",
        default="/sdcard/all.txt",
        help="File containing patterns separated by empty lines",
    )
    args = ap.parse_args()
    patterns = load_patterns_from_file(args.file)
    print(f"Loaded {len(patterns)} usable patterns from {args.file}")
    clean_dir_mp(args.path, patterns)
