import re
import sys
import time
from io import BytesIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import pycurl
from packaging.version import Version

MIRROR_URL = "https://mirror-pypi.runflare.com"
TIMEOUT = 30
DOWNLOAD_DIR = Path.cwd()
NUM_CHUNKS = 8
CHUNK_SIZE = 1024 * 1024
lock = threading.Lock()


def fetch_package_page(pkg_name: str) -> str:
    url = f"{MIRROR_URL}/{pkg_name}/json"
    buffer = BytesIO()

    curl = pycurl.Curl()
    curl.setopt(curl.URL, url)
    curl.setopt(curl.WRITEDATA, buffer)
    curl.setopt(curl.FOLLOWLOCATION, 1)
    curl.setopt(curl.TIMEOUT, TIMEOUT)
    curl.setopt(curl.USERAGENT, "Package-Downloader/1.0")

    try:
        curl.perform()
        response_code = curl.getinfo(curl.RESPONSE_CODE)

        if response_code != 200:
            print(f"Error: HTTP {response_code} for {pkg_name}")
            return ""

        return buffer.getvalue().decode("utf-8")
    except Exception as e:
        print(f"Error fetching page for {pkg_name}: {e}")
        return ""
    finally:
        curl.close()


def extract_download_urls(html: str, pkg_name: str) -> list[tuple[str, Version, str]]:
    pattern = re.compile(r'<a href="([^"]+)"[^>]*>([^<]+\.(?:whl|tar\.gz|zip))</a>', re.IGNORECASE)

    packages = []
    for match in pattern.finditer(html):
        url = match.group(1)
        filename = match.group(2)

        version_pattern = re.compile(
            rf"{re.escape(pkg_name.replace('-', '[_-]'))}[_-](\d+[A-Za-z0-9\.\-_]*)\.(whl|tar\.gz|zip)",
            re.IGNORECASE,
        )
        version_match = version_pattern.search(filename)

        if version_match:
            version_str = version_match.group(1)
            file_type = version_match.group(2)

            try:
                version = Version(version_str)
                packages.append((url, version, file_type))
            except:
                continue

    return packages


def get_latest_download_info(html: str, pkg_name: str) -> tuple[str, str, Version] | None:
    packages = extract_download_urls(html, pkg_name)

    if not packages:
        return None

    packages.sort(key=lambda x: x[1], reverse=True)
    latest_packages = [p for p in packages if p[1] == packages[0][1]]

    preferred_order = {"tar.gz": 0, "whl": 1, "zip": 2}
    latest_packages.sort(key=lambda x: preferred_order.get(x[2], 3))

    best_package = latest_packages[0]
    url, version, file_type = best_package

    filename = url.split("/")[-1].split("#")[0]

    return (url, filename, version)


def get_file_size(url: str) -> int:
    curl = pycurl.Curl()
    curl.setopt(curl.URL, url)
    curl.setopt(curl.NOBODY, 1)
    curl.setopt(curl.FOLLOWLOCATION, 1)
    curl.setopt(curl.TIMEOUT, TIMEOUT)
    curl.setopt(curl.USERAGENT, "Package-Downloader/1.0")

    try:
        curl.perform()
        content_length = curl.getinfo(curl.CONTENT_LENGTH_DOWNLOAD)
        return int(content_length) if content_length > 0 else 0
    except:
        return 0
    finally:
        curl.close()


def download_chunk(url: str, start_byte: int, end_byte: int, chunk_index: int) -> tuple[int, bytes]:
    buffer = BytesIO()
    curl = pycurl.Curl()
    curl.setopt(curl.URL, url)
    curl.setopt(curl.WRITEDATA, buffer)
    curl.setopt(curl.FOLLOWLOCATION, 1)
    curl.setopt(curl.TIMEOUT, 60)
    curl.setopt(curl.USERAGENT, "Package-Downloader/1.0")

    curl.setopt(curl.RANGE, f"{start_byte}-{end_byte}")

    try:
        curl.perform()
        response_code = curl.getinfo(curl.RESPONSE_CODE)

        if response_code not in [200, 206]:
            return (chunk_index, b"")

        return (chunk_index, buffer.getvalue())
    except Exception as e:
        print(f"  Error downloading chunk {chunk_index}: {e}")
        return (chunk_index, b"")
    finally:
        curl.close()


def download_file_multithreaded(url: str, filename: str) -> bool:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DOWNLOAD_DIR / filename

    if output_path.exists():
        print(f"  File already exists: {filename}")
        return True

    print(f"  Downloading: {filename}")

    file_size = get_file_size(url)
    if file_size <= 0:
        print(f"  Could not determine file size, falling back to single download")
        return download_file_single(url, filename)

    print(f"  File size: {file_size / (1024 * 1024):.2f} MB")

    chunk_size = max(file_size // NUM_CHUNKS, 1024 * 1024)
    chunks = []

    for i in range(0, file_size, chunk_size):
        start = i
        end = min(i + chunk_size - 1, file_size - 1)
        chunks.append((start, end))

    downloaded_chunks = {}
    total_downloaded = 0
    start_time = time.time()
    last_update_time = start_time

    print(f"  Downloading in {len(chunks)} chunks...")

    with ThreadPoolExecutor(max_workers=NUM_CHUNKS) as executor:
        future_to_chunk = {
            executor.submit(download_chunk, url, start, end, idx): (start, end)
            for idx, (start, end) in enumerate(chunks)
        }

        for future in as_completed(future_to_chunk):
            chunk_index, data = future.result()
            start, end = future_to_chunk[future]

            with lock:
                downloaded_chunks[chunk_index] = (start, data)
                total_downloaded += len(data)

                current_time = time.time()
                if current_time - last_update_time >= 0.5:
                    elapsed = current_time - start_time
                    speed = total_downloaded / elapsed if elapsed > 0 else 0
                    remaining = file_size - total_downloaded
                    eta = remaining / speed if speed > 0 else 0

                    progress = (total_downloaded / file_size) * 100

                    print(
                        f"\r  Progress: {progress:.1f}% | "
                        f"{total_downloaded / (1024 * 1024):.2f}/{file_size / (1024 * 1024):.2f} MB | "
                        f"Speed: {speed / (1024 * 1024):.2f} MB/s | "
                        f"ETA: {eta:.1f}s",
                        end="",
                    )
                    last_update_time = current_time

    print()

    if len(downloaded_chunks) != len(chunks):
        print(f"  Error: Only {len(downloaded_chunks)}/{len(chunks)} chunks downloaded")
        return False

    print(f"  Assembling file...")
    try:
        with open(output_path, "wb") as f:
            for i in range(len(chunks)):
                start, data = downloaded_chunks[i]
                f.write(data)

        if output_path.stat().st_size != file_size:
            print(f"  Error: File size mismatch. Expected {file_size}, got {output_path.stat().st_size}")
            output_path.unlink()
            return False

        elapsed = time.time() - start_time
        speed = file_size / elapsed / (1024 * 1024)
        print(f"  Downloaded successfully: {filename}")
        print(f"  Total time: {elapsed:.2f}s | Average speed: {speed:.2f} MB/s")
        return True

    except Exception as e:
        print(f"  Error writing file {filename}: {e}")
        if output_path.exists():
            output_path.unlink()
        return False


def download_file_single(url: str, filename: str) -> bool:
    output_path = DOWNLOAD_DIR / filename

    print(f"  Downloading (single thread): {filename}")

    start_time = time.time()
    last_update_time = start_time

    with open(output_path, "wb") as f:
        curl = pycurl.Curl()
        curl.setopt(curl.URL, url)
        curl.setopt(curl.WRITEDATA, f)
        curl.setopt(curl.FOLLOWLOCATION, 1)
        curl.setopt(curl.TIMEOUT, 60)
        curl.setopt(curl.USERAGENT, "Package-Downloader/1.0")

        def progress_callback(download_t, download_d, upload_t, upload_d):
            nonlocal last_update_time
            current_time = time.time()
            if current_time - last_update_time >= 0.5:
                elapsed = current_time - start_time
                speed = download_d / elapsed if elapsed > 0 else 0
                remaining = download_t - download_d
                eta = remaining / speed if speed > 0 else 0

                progress = (download_d / download_t * 100) if download_t > 0 else 0

                print(
                    f"\r  Progress: {progress:.1f}% | "
                    f"{download_d / (1024 * 1024):.2f}/{download_t / (1024 * 1024):.2f} MB | "
                    f"Speed: {speed / (1024 * 1024):.2f} MB/s | "
                    f"ETA: {eta:.1f}s",
                    end="",
                )
                last_update_time = current_time
            return 0

        curl.setopt(curl.NOPROGRESS, 0)
        curl.setopt(curl.XFERINFOFUNCTION, progress_callback)

        try:
            curl.perform()
            response_code = curl.getinfo(curl.RESPONSE_CODE)

            if response_code != 200:
                print(f"\n  Error: HTTP {response_code} while downloading {filename}")
                if output_path.exists():
                    output_path.unlink()
                return False

            print()
            elapsed = time.time() - start_time
            file_size = output_path.stat().st_size
            speed = file_size / elapsed / (1024 * 1024)
            print(f"  Downloaded successfully: {filename}")
            print(f"  Total time: {elapsed:.2f}s | Average speed: {speed:.2f} MB/s")
            return True

        except Exception as e:
            print(f"\n  Error downloading {filename}: {e}")
            if output_path.exists():
                output_path.unlink()
            return False
        finally:
            curl.close()


def download_file(url: str, filename: str) -> bool:
    file_size = get_file_size(url)

    if file_size > 5 * 1024 * 1024:
        return download_file_multithreaded(url, filename)
    else:
        return download_file_single(url, filename)


def process_package(pkg_name: str) -> bool:
    print(f"\n{'=' * 40}")
    print(f"Processing package: {pkg_name}")
    print(f"{'=' * 40}")

    print(f"Fetching package info for {pkg_name}...")
    html = fetch_package_page(pkg_name)

    if not html:
        print(f"Failed to fetch package info for {pkg_name}")
        return False

    download_info = get_latest_download_info(html, pkg_name)

    if not download_info:
        print(f"No valid download links found for {pkg_name}")
        return False

    url, filename, version = download_info
    print(f"Latest version: {version}")
    print(f"File: {filename}")

    return download_file(url, filename)


def main():
    if len(sys.argv) < 2:
        print("Usage: python pyget.py <package1> [package2] [package3] ...")
        print("Example: python pyget.py requests wheel setuptools")
        sys.exit(1)

    packages = sys.argv[1:]
    print(f"Packages to download: {', '.join(packages)}")
    print(f"Download directory: {DOWNLOAD_DIR}")
    print(f"Using {NUM_CHUNKS} parallel chunks for large files")

    start_time = time.time()
    successful = []
    failed = []

    for pkg_name in packages:
        try:
            if process_package(pkg_name):
                successful.append(pkg_name)
            else:
                failed.append(pkg_name)
        except Exception as e:
            print(f"Unexpected error processing {pkg_name}: {e}")
            failed.append(pkg_name)

    print(f"\n{'=' * 40}")
    print("DOWNLOAD SUMMARY")
    print(f"{'=' * 40}")
    print(f"Total packages: {len(packages)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")

    if successful:
        print(f"\nSuccessfully downloaded:")
        for pkg in successful:
            print(f"  ✓ {pkg}")

    if failed:
        print(f"\nFailed to download:")
        for pkg in failed:
            print(f"  ✗ {pkg}")

    end_time = time.time()
    print(f"\nFinished in {end_time - start_time:.2f} seconds")


if __name__ == "__main__":
    main()
