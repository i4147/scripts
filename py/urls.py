from __future__ import annotations

import os
import re
import tarfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse, urlunparse

from dh import get_files

if TYPE_CHECKING:
    from collections.abc import Iterable
try:
    import zstandard as zstd
except Exception:
    zstd = None
URL_RE = re.compile(r"""(https?://[^\s<>"\']+|\bwww\.[^\s<>"\']+\b|\b[^\s<>"\']+\.(com|net|org)[^\s<>"\']*)""")
GITHUB_RE = re.compile(r"(?i)github\.com")
MAX_WORKERS = 8
all_urls: set[str] = set()
git_urls: set[str] = set()
git_urls_classified: dict[str, set[str]] = {
    "repo": set(),
    "issue": set(),
    "pull": set(),
    "release": set(),
    "raw": set(),
    "clone": set(),
    "other": set(),
}
lock = threading.Lock()


def normalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        scheme = p.scheme.lower()
        netloc = p.netloc.lower()
        if (scheme == "http" and netloc.endswith(":80")) or (scheme == "https" and netloc.endswith(":443")):
            netloc = netloc.rsplit(":", 1)[0]
        path = p.path.rstrip("/") or "/"
        return urlunparse((
            scheme,
            netloc,
            path,
            "",
            p.query,
            "",
        ))
    except Exception:
        return url


def classify_github_url(url: str) -> str:
    try:
        p = urlparse(url)
        path = p.path.lower()
        if p.netloc.startswith("raw.githubusercontent.com"):
            return "raw"
        if url.endswith(".git"):
            return "clone"
        if "/issues/" in path:
            return "issue"
        if "/pull/" in path or "/pulls/" in path:
            return "pull"
        if "/releases" in path:
            return "release"
        parts = [x for x in path.split("/") if x]
        if len(parts) >= 2:
            return "repo"
        return "other"
    except Exception:
        return "other"


def extract_urls_from_bytes(
    data: bytes,
) -> set[str]:
    try:
        text = data.decode("utf-8", errors="ignore")
        return {normalize_url(u) for u in URL_RE.findall(text)}
    except Exception:
        return set()


def handle_file_bytes(data: bytes) -> None:
    urls = extract_urls_from_bytes(data)
    if not urls:
        return
    else:
        print(urls)
    with lock:
        for u in urls:
            all_urls.add(u)
            if GITHUB_RE.search(u):
                git_urls.add(u)
                cat = classify_github_url(u)
                git_urls_classified[cat].add(u)


def process_regular_file(path: str) -> None:
    try:
        with Path(path).open("rb") as f:
            handle_file_bytes(f.read())
    except Exception:
        pass


def process_zip(path: str) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                try:
                    handle_file_bytes(z.read(name))
                except Exception:
                    continue
    except Exception:
        pass


def process_tar(path: str) -> None:
    try:
        with tarfile.open(path, "r:*") as t:
            for m in t.getmembers():
                if m.isfile():
                    try:
                        f = t.extractfile(m)
                        if f:
                            handle_file_bytes(f.read())
                    except Exception:
                        continue
    except Exception:
        pass


def process_tar_zst(path: str) -> None:
    if not zstd:
        return
    try:
        with Path(path).open("rb") as f:
            dctx = zstd.ZstdDecompressor()
            stream = dctx.stream_reader(f)
            with tarfile.open(fileobj=stream, mode="r|*") as t:
                for m in t:
                    if m.isfile():
                        try:
                            f2 = t.extractfile(m)
                            if f2:
                                handle_file_bytes(f2.read())
                        except Exception:
                            continue
    except Exception:
        pass


def process_path(path: str) -> None:
    p = path.lower()
    if p.endswith((".zip", ".whl")):
        process_zip(path)
    elif p.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar.bz2")):
        process_tar(path)
    elif p.endswith(".tar.zst"):
        process_tar_zst(path)
    else:
        process_regular_file(path)


def iter_files(root: str) -> Iterable[str]:
    for base, _, files in os.walk(root):
        for f in files:
            yield os.path.join(base, f)


def main() -> None:
    cwd = Path.cwd()
    files = get_files(cwd)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(process_path, f) for f in files]
        for _ in as_completed(futures):
            pass
    with Path("/sdcard/urls.txt").open("a", encoding="utf-8") as f:
        f.writelines(u + "\n" for u in sorted(all_urls))
    with Path("/sdcard/giturls.txt").open("a", encoding="utf-8") as f:
        f.writelines(u + "\n" for u in sorted(git_urls))
    with Path("/sdcard/giturls_classified.txt").open("a", encoding="utf-8") as f:
        for (
            cat,
            urls,
        ) in git_urls_classified.items():
            f.writelines(f"{cat}\t{u}\n" for u in sorted(urls))


if __name__ == "__main__":
    main()
