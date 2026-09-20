from __future__ import annotations

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from tqdm import tqdm

MAX_WORKERS = 4
MAX_RETRIES = 3
TIMEOUT = 60
OUTPUT_DIR = "downloads"
URLS_FILE = "urls.txt"
SAFE_EXTENSIONS = [
    r"\.ttf$",
    r"\.woff$",
    r"\.woff2$",
    r"\.eot$",
    r"\.otf$",
    r"\.min\.css$",
    r"\.min\.js$",
    r"\.css$",
    r"\.js$",
    r"\.pdf$",
    r"\.html?$",
    r"\.whl$",
    r"\.tar\.(gz|xz|zst|bz2|lzma|7z)$",
    r"\.zip$",
]
EXT_PATTERN = re.compile(r"|".join(SAFE_EXTENSIONS), re.IGNORECASE)


def sanitize_filename(name) -> str:
    name = unquote(name)
    name = re.sub(r'[<>:"|?*]', "_", name)
    return name[:255].strip() or "downloaded_file"


def extract_filename(url) -> str:
    parsed = urlparse(url)
    path = parsed.path
    filename = path.split("/")[-1] or "index.html"
    filename = filename.split("#")[0]
    filename = filename.split("?")[0]
    filename = sanitize_filename(filename)
    if not re.search(r"\.[a-zA-Z0-9]+$", filename):
        filename += ".dat"
    return filename


def is_safe_extension(url) -> bool:
    parsed = urlparse(url)
    path = parsed.path
    filename = path.split("/")[-1]
    base_name = filename.split("?")[0].split("#")[0]
    return bool(EXT_PATTERN.search(base_name))


def get_filesize(url, session) -> int | None:
    try:
        r = session.head(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        size = r.headers.get("Content-Length")
        return int(size) if size else None
    except Exception:
        return None


def download_one(url, session, output_dir, resume_from=None):
    filename = extract_filename(url)
    filepath = os.path.join(output_dir, filename)
    offset = 0
    if resume_from and Path(filepath).exists():
        offset = Path(filepath).stat().st_size
        remote_size = get_filesize(url, session)
        if remote_size is not None and offset >= remote_size:
            return url, True, f"Already complete ({offset} bytes)"
    headers = {}
    if offset > 0:
        headers["Range"] = f"bytes={offset}-"
    try:
        with session.get(url, timeout=TIMEOUT, headers=headers, stream=True) as r:
            r.raise_for_status()
            content_length = int(r.headers.get("Content-Length", 0))
            content_length + offset if content_length else None
            mode = "ab" if offset else "wb"
            with Path(filepath).open(mode) as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        return url, True, filepath
    except requests.exceptions.RequestException as e:
        if MAX_RETRIES > 0:
            return url, False, f"Retry needed: {e}"
        return url, False, str(e)


def download_urls(urls: list[str], output_dir=OUTPUT_DIR) -> None:
    Path(output_dir).mkdir(exist_ok=True, parents=True)
    safe_urls = [url for url in urls if is_safe_extension(url)]
    skipped = len(urls) - len(safe_urls)
    if skipped > 0:
        print(f"⚠️  Skipped {skipped} URLs (not matching safe extensions).")
    if not safe_urls:
        print("❌ No valid URLs to download.")
        return
    print(f"🚀 Starting download of {len(safe_urls)} URLs...\n")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ResumableDownloader/1.0)"})
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {executor.submit(download_one, url, session, output_dir): url for url in safe_urls}
        with tqdm(total=len(safe_urls), desc="Downloading", unit="file") as pbar:
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    url, success, result = future.result()
                    if success:
                        pbar.write(f"✅ {url.split('?')[0]} → {result}")
                    else:
                        pbar.write(f"❌ {url.split('?')[0]} failed: {result}")
                except Exception as e:
                    pbar.write(f"⚠️  Unexpected error for {url}: {e}")
                pbar.update(1)
    session.close()


if __name__ == "__main__":
    urls = []
    try:
        with Path(URLS_FILE).open("r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        print(f"❌ Error: {URLS_FILE} not found.")
        sys.exit(1)
    if not urls:
        print(f"⚠️  No URLs found in {URLS_FILE}.")
        sys.exit(0)
    if len(sys.argv) > 1:
        URLS_FILE = sys.argv[1]
        print(f"Using input file: {URLS_FILE}")
        download_urls(urls)
    print("\n✅ All downloads completed.")
