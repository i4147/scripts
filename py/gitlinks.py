from dh import URL_REGEX
import contextlib
import os
import tarfile
import zipfile
from multiprocessing import get_context
from pathlib import Path

OUTPUT_FILE = "/sdcard/gitlinks.txt"
ARCHIVE_EXTENSIONS = (
    ".zip",
    ".whl",
    ".tar.gz",
    ".tgz",
    ".tar.xz",
    ".txz",
)


def extract_git_urls_from_bytes(data: bytes):
    urls = set()
    for match in URL_REGEX.findall(data):
        with contextlib.suppress(Exception):
            urls.add(match.decode("utf-8", errors="ignore"))
    return urls


def process_regular_file(path):
    try:
        data = Path(path).read_bytes()
        return extract_git_urls_from_bytes(data)
    except Exception:
        return set()


def process_zip(path):
    urls = set()
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                try:
                    with z.open(name) as f:
                        data = f.read()
                        urls |= extract_git_urls_from_bytes(data)
                except Exception:
                    continue
    except Exception:
        pass
    return urls


def process_tar(path, mode: str):
    urls = set()
    try:
        with tarfile.open(path, mode) as t:
            for member in t.getmembers():
                if member.isfile():
                    try:
                        f = t.extractfile(member)
                        if f:
                            data = f.read()
                            urls |= extract_git_urls_from_bytes(data)
                    except Exception:
                        continue
    except Exception:
        pass
    return urls


def process_archive(path):
    lower = path.lower()
    if lower.endswith((".zip", ".whl")):
        return process_zip(path)
    if lower.endswith((".tar.gz", ".tgz")):
        return process_tar(path, "r:gz")
    if lower.endswith((".tar.xz", ".txz")):
        return process_tar(path, "r:xz")
    return set()


def worker(path):
    try:
        if path.lower().endswith(ARCHIVE_EXTENSIONS):
            return process_archive(path)
        return process_regular_file(path)
    except Exception:
        return set()


def collect_files():
    all_files = []
    for root, _dirs, files in os.walk("."):
        for f in files:
            full = os.path.join(root, f)
            all_files.append(full)
    return all_files


def main() -> None:
    files = collect_files()
    print(f"Found {len(files)} files")
    found_urls = set()
    with get_context("spawn").Pool(8) as pool:
        for urls in pool.imap_unordered(worker, files):
            if urls:
                found_urls |= urls
    if found_urls:
        with Path(OUTPUT_FILE).open("a", encoding="utf-8") as out:
            out.writelines(url + "\n" for url in sorted(found_urls))
        print(f"\nExtracted {len(found_urls)} unique git URLs → {OUTPUT_FILE}")
    else:
        print(f"\nno link")


if __name__ == "__main__":
    main()
