import re
import sys
import tarfile
import zipfile
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
import py7zr
from dh import cprint, get_nobinary
from loguru import logger

CHUNK_SIZE = 1024 * 1024
POOL_SIZE = 8
URL_PATTERN = re.compile(
    r"""https?://[^\s"'<>\)\]\}]+""",
    re.IGNORECASE,
)
GITHUB_PATTERN = re.compile(
    r"""https?://(?:www\.)?github\.com/[^\s"'<>\)\]\}]+""",
    re.IGNORECASE,
)
ARCHIVE_SUFFIXES_ZIP = {".zip", ".whl"}
ARCHIVE_SUFFIXES_TAR = {
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.xz",
    ".txz",
    ".tar.zst",
    ".tar.7z",
    ".tar.bz2",
    ".tbz",
    ".tbz2",
}
ARCHIVE_SUFFIXES_7Z = {".7z"}
OUTPUT_ALL = Path("/sdcard/data/urlzz.txt")
OUTPUT_GIT = Path("/sdcard/data/gitlinks.txt")


def extract_urls_from_text(content):
    result = set(URL_PATTERN.findall(content))
    cprint(result)
    return result


def extract_urls_from_file(path):
    urls = set()
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        urls.update(extract_urls_from_text(content))
    except Exception as exc:
        logger.warning(f"Failed to read {path}: {exc}")
    return urls


def extract_urls_from_tar(path):
    urls = set()
    try:
        with tarfile.open(path, mode="r:*") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                fileobj = tar.extractfile(member)
                if fileobj is None:
                    continue
                content = fileobj.read().decode("utf-8", errors="ignore")
                urls.update(extract_urls_from_text(content))
    except Exception as exc:
        logger.warning(f"Failed to read tar {path}: {exc}")
    return urls


def extract_urls_from_zip(path):
    urls = set()
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                try:
                    with zf.open(name) as f:
                        content = f.read().decode("utf-8", errors="ignore")
                        urls.update(extract_urls_from_text(content))
                except Exception:
                    continue
    except Exception as exc:
        logger.warning(f"Failed to read zip {path}: {exc}")
    return urls


def extract_urls_from_7z(path):
    urls = set()
    try:
        with py7zr.SevenZipFile(path, mode="r") as archive:
            all_files = archive.readall()
            for bio in all_files.values():
                try:
                    content = bio.read().decode("utf-8", errors="ignore")
                    urls.update(extract_urls_from_text(content))
                except Exception:
                    continue
    except Exception as exc:
        logger.warning(f"Failed to read 7z {path}: {exc}")
    return urls


def extract_urls(path):
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix in ARCHIVE_SUFFIXES_ZIP:
        return extract_urls_from_zip(path)
    if suffix in ARCHIVE_SUFFIXES_7Z:
        return extract_urls_from_7z(path)
    if suffix in ARCHIVE_SUFFIXES_TAR or any(name.endswith(s) for s in ARCHIVE_SUFFIXES_TAR):
        return extract_urls_from_tar(path)
    return extract_urls_from_file(path)


def _worker(path):
    return extract_urls(path)


def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    paths = [Path(p) for p in args] if args else list(get_nobinary(cwd))
    paths = list(paths)
    all_urls = set()
    with Pool(processes=POOL_SIZE) as pool:
        async_results = [pool.apply_async(_worker, (path,)) for path in paths]
        result = None
        for result in async_results:
            try:
                all_urls.update(result.get())
            except Exception as exc:
                logger.warning(f"Worker failed: {exc}")
    github_urls = {u for u in all_urls if GITHUB_PATTERN.match(u)}
    OUTPUT_ALL.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_ALL.open("a", encoding="utf-8") as f:
        f.write("\n")
        f.writelines(url + "\n" for url in sorted(all_urls))
    with OUTPUT_GIT.open("a", encoding="utf-8") as f:
        f.write("\n")
        f.writelines(url + "\n" for url in sorted(github_urls))
    print(f"Extracted {len(all_urls)} unique URLs to {OUTPUT_ALL}")
    print(f"Extracted {len(github_urls)} GitHub URLs to {OUTPUT_GIT}")


if __name__ == "__main__":
    main()
