from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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
        print("Error: Neither pycurl nor requests is installed!")
        print("Run: pip install pycurl requests")
        sys.exit(1)


def download_file(url: str, filepath: Path, timeout: int = 120) -> bool:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    if HAS_PYCURL:
        try:
            with open(filepath, "wb") as f:
                c = pycurl.Curl()
                c.setopt(c.URL, url)
                c.setopt(c.WRITEDATA, f)
                c.setopt(c.TIMEOUT, timeout)
                c.setopt(c.FOLLOWLOCATION, True)
                c.setopt(c.MAXREDIRS, 5)
                c.setopt(c.USERAGENT, "Mozilla/5.0")
                c.perform()
                c.close()
            print(f"✅ Downloaded (pycurl): {filepath.name}")
            return True
        except Exception as e:
            print(f"⚠️  pycurl failed for {filepath.name}: {e}. Trying requests...")
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
            with open(filepath, "wb") as f:
                f.writelines(response.iter_content(chunk_size=8192))
        print(f"✅ Downloaded (requests): {filepath.name}")
        return True
    except Exception as e:
        print(f"❌ Failed {filepath.name}: {e}")
        return False


def main():
    urls_file = Path("urls.txt")
    if not urls_file.exists():
        print(f"Error: {urls_file} not found!")
        sys.exit(1)
    original_lines = urls_file.read_text(encoding="utf-8").splitlines()
    download_tasks = []
    url_to_line = {}
    for line in original_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            url = stripped.split()[0]
            filename = url.split("/")[-1].split("?")[0] or f"download_{len(download_tasks) + 1}"
            filepath = Path("downloads") / filename
            download_tasks.append((url, filepath))
            url_to_line[url] = line
    if not download_tasks:
        print("No valid URLs found in urls.txt")
        sys.exit(0)
    print(f"Found {len(download_tasks)} files to download.\n")
    successful_urls = set()
    max_workers = min(12, len(download_tasks))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(download_file, url, path): url for url, path in download_tasks}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                if future.result():
                    successful_urls.add(url)
            except Exception as exc:
                print(f"Unexpected error with {url}: {exc}")
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
    print("\n" + "=" * 40)
    print("Download session completed!")
    print(f"✅ Successfully downloaded : {removed_count} files")
    print(f"❌ Remaining in urls.txt   : {len(download_tasks) - removed_count} files")
    print("-" * 40)


if __name__ == "__main__":
    raise SystemExit(main())
