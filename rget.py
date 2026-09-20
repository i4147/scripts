import re
import sys
from collections.abc import Iterable
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from urllib.parse import unquote, urlparse
import requests
from loguru import logger
from tqdm import tqdm
MAX_WORKERS = 8
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
def sanitize_filename(name):
    name = unquote(name)
    name = re.sub(r'[<>:"|?*]', "_", name)
    return name[:255].strip() or "downloaded_file"
def extract_filename(url):
    parsed = urlparse(url)
    path = parsed.path
    filename = path.split("/")[-1] or "index.html"
    filename = filename.split("#")[0]
    filename = filename.split("?")[0]
    filename = sanitize_filename(filename)
    if not re.search(r"\.[a-zA-Z0-9]+$", filename):
        filename += ".dat"
    return filename
def is_safe_extension(url):
    parsed = urlparse(url)
    path = parsed.path
    filename = path.split("/")[-1]
    base_name = filename.split("?")[0].split("#")[0]
    return bool(EXT_PATTERN.search(base_name))
def get_filesize(url, session):
    try:
        r = session.head(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        size = r.headers.get("Content-Length")
        return int(size) if size else None
    except Exception:
        return None
def download_one(
    url,
    session,
    output_dir,
    resume_from=None,
):
    filename = extract_filename(url)
    path = Path(output_dir) / filename
    offset = 0
    if resume_from and path.exists():
        offset = path.stat().st_size
        remote_size = get_filesize(url, session)
        if remote_size is not None and offset >= remote_size:
            return url, True, f"Already complete ({offset} bytes)"
    headers = {}
    if offset > 0:
        headers["Range"] = f"bytes={offset}-"
    try:
        with session.get(url, timeout=TIMEOUT, headers=headers, stream=True) as r:
            r.raise_for_status()
            mode = "ab" if offset else "wb"
            with path.open(mode) as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
        return url, True, str(path)
    except requests.exceptions.RequestException as e:
        if MAX_RETRIES > 0:
            return url, False, f"Retry needed: {e}"
        return url, False, str(e)
def _make_session():
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (compatible; ResumableDownloader/1.0)"}
    )
    return session
def download_urls(urls, output_dir=OUTPUT_DIR):
    Path(output_dir).mkdir(exist_ok=True, parents=True)
    safe_urls = [url for url in urls if is_safe_extension(url)]
    skipped = len(urls) - len(safe_urls)
    if skipped > 0:
        logger.warning(f"Skipped {skipped} URLs (not matching safe extensions).")
    if not safe_urls:
        logger.error("No valid URLs to download.")
        return
    print(f"Starting download of {len(safe_urls)} URLs...")
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [
            pool.apply_async(download_one, (url, _make_session(), output_dir))
            for url in safe_urls
        ]
        with tqdm(total=len(safe_urls), desc="Downloading", unit="file") as pbar:
            for url, ar in zip(safe_urls, async_results):
                try:
                    _, success, result = ar.get()
                    if success:
                        pbar.write(f"✅ {url.split('?')[0]} → {result}")
                    else:
                        pbar.write(f"❌ {url.split('?')[0]} failed: {result}")
                except Exception as e:
                    pbar.write(f"⚠️  Unexpected error for {url}: {e}")
                pbar.update(1)
def _read_urls(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]
def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    urls_file = args[0] if args else URLS_FILE
    if urls_file != URLS_FILE:
        print(f"Using input file: {urls_file}")
    try:
        urls = _read_urls(urls_file)
    except FileNotFoundError:
        logger.error(f"{urls_file} not found.")
        return 1
    if not urls:
        logger.warning(f"No URLs found in {urls_file}.")
        return 0
    download_urls(urls)
    print("All downloads completed.")
    return 0
if __name__ == "__main__":
    sys.exit(main())
