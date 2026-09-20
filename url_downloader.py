import sys
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Set
from loguru import logger
try:
    import pycurl  
    HAS_PYCURL = True
    print("Using pycurl backend")
except ImportError:
    HAS_PYCURL = False
    try:
        import requests
        print("pycurl not available → falling back to requests")
    except ImportError:
        logger.error("Neither pycurl nor requests is installed!")
        logger.error("Run: pip install pycurl requests")
        sys.exit(1)
MAX_WORKERS = 8
DEFAULT_TIMEOUT = 120
URLS_FILE = Path("urls.txt")
DOWNLOADS_DIR = Path("downloads")
def download_file(url, path, timeout=DEFAULT_TIMEOUT):
    path.parent.mkdir(parents=True, exist_ok=True)
    if HAS_PYCURL:
        try:
            with open(path, "wb") as f:
                c = pycurl.Curl()
                c.setopt(c.URL, url)
                c.setopt(c.WRITEDATA, f)
                c.setopt(c.TIMEOUT, timeout)
                c.setopt(c.FOLLOWLOCATION, True)
                c.setopt(c.MAXREDIRS, 5)
                c.setopt(c.USERAGENT, "Mozilla/5.0")
                c.perform()
                c.close()
            logger.success(f"Downloaded (pycurl): {path.name}")
            return True
        except Exception as e:
            logger.warning(f"pycurl failed for {path.name}: {e}. Trying requests...")
    try:
        with requests.Session() as session:
            response = session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=timeout,
                stream=True,
                allow_redirects=True,
            )
            response.raise_for_status()
            with open(path, "wb") as f:
                f.writelines(response.iter_content(chunk_size=8192))
        logger.success(f"Downloaded (requests): {path.name}")
        return True
    except Exception as e:
        logger.error(f"Failed {path.name}: {e}")
        return False
def parse_urls_file(urls_file):
    original_lines = urls_file.read_text(encoding="utf-8").splitlines()
    download_tasks = []
    for line in original_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            url = stripped.split()[0]
            filename = (
                url.split("/")[-1].split("?")[0]
                or f"download_{len(download_tasks) + 1}"
            )
            path = DOWNLOADS_DIR / filename
            download_tasks.append((url, path))
    return original_lines, download_tasks
def update_urls_file(
    urls_file,
    original_lines,
    successful_urls,
):
    remaining_lines = []
    removed_count = 0
    for line in original_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            url = stripped.split()[0]
            if url in successful_urls:
                removed_count += 1
                continue
        remaining_lines.append(line)
    urls_file.write_text("\n".join(remaining_lines) + "\n", encoding="utf-8")
    return removed_count
def main():
    if not URLS_FILE.exists():
        logger.error(f"{URLS_FILE} not found!")
        return 1
    original_lines, download_tasks = parse_urls_file(URLS_FILE)
    if not download_tasks:
        print("No valid URLs found in urls.txt")
        return 0
    print(f"Found {len(download_tasks)} files to download.\n")
    successful_urls = set()
    results = []
    with Pool(processes=MAX_WORKERS) as pool:
        for url, path in download_tasks:
            async_result = pool.apply_async(download_file, (url, path))
            results.append((url, async_result))
        for url, async_result in results:
            try:
                if async_result.get():
                    successful_urls.add(url)
            except Exception as exc:
                logger.error(f"Unexpected error with {url}: {exc}")
    removed_count = update_urls_file(URLS_FILE, original_lines, successful_urls)
    print("=" * 40)
    print("Download session completed!")
    print(f"✅ Successfully downloaded : {removed_count} files")
    print(f"❌ Remaining in urls.txt   : {len(download_tasks) - removed_count} files")
    print("-" * 40)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
