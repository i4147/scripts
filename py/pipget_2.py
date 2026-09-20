import re
import sys
import time
from io import BytesIO
from pathlib import Path

import pycurl
from bs4 import BeautifulSoup
from dh import cprint

MIRROR_URLS = [
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://pypi.org/simple",
]
TIMEOUT = 30
DOWNLOAD_DIR = Path.cwd()
MAX_RETRIES = 3
RETRY_DELAY = 2

ARCH_TAGS = [
    "win32",
    "win_amd64",
    "win_arm64",
    "win32",
    "windows",
    "manylinux",
    "musllinux",
    "linux_i686",
    "linux_x86_64",
    "linux_armv7l",
    "linux_aarch64",
    "linux_armv6l",
    "linux_armv8l",
    "macosx",
    "darwin",
    "x86_64",
    "amd64",
    "i686",
    "i386",
    "aarch64",
    "armv7l",
    "armv6l",
    "armv8l",
    "ppc64",
    "ppc64le",
    "s390x",
    "riscv64",
    "cp36",
    "cp37",
    "cp38",
    "cp39",
    "cp310",
    "cp311",
    "cp312",
    "cp313",
    "cp27",
    "cp35",
    "pp27",
    "pp36",
    "pp37",
    "pp38",
    "pp39",
    "pypy",
    "jython",
    "32",
    "64",
]

WHEEL_PLATFORM_RE = re.compile(
    r"-(cp\d+|pp\d+|py\d+)"
    r"(-(cp\d+|pp\d+|py\d+))?"
    r"-(manylinux|musllinux|win|macosx|linux|darwin)",
    re.IGNORECASE,
)


def human_size(num_bytes: int) -> str:
    if num_bytes is None or num_bytes < 0:
        return "unknown"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def is_windows_url(url: str) -> bool:
    lower = url.lower()
    return "win32" in lower or "win_amd64" in lower or "win_arm64" in lower or "-win-" in lower


def has_arch_tag(url: str) -> bool:
    lower = url.lower()
    if WHEEL_PLATFORM_RE.search(lower):
        return True
    for tag in [
        "manylinux",
        "musllinux",
        "macosx",
        "darwin",
        "x86_64",
        "amd64",
        "i686",
        "aarch64",
        "armv7l",
        "armv6l",
        "armv8l",
        "ppc64",
        "s390x",
        "riscv64",
    ]:
        if tag in lower:
            return True
    return False


def is_sdist(url: str) -> bool:
    return url.lower().endswith(".tar.gz")


def is_pure_wheel(url: str) -> bool:
    lower = url.lower()
    if not lower.endswith(".whl"):
        return False
    return "py3-none-any" in lower or "py2.py3-none-any" in lower


def select_best_url(links: list, pkg_name: str) -> tuple[str, str, str] | None:
    sdist_candidates = []
    pure_wheel_candidates = []
    arch_skipped = []

    for link in links:
        href = link.get("href", "").strip()
        if not href:
            continue
        url = href.split("#")[0]
        filename = link.get_text().strip() or url.split("/")[-1]

        if is_windows_url(url):
            continue

        if has_arch_tag(url):
            arch_skipped.append((url, filename))
            continue

        if is_sdist(url):
            sdist_candidates.append((url, filename))
        elif is_pure_wheel(url):
            pure_wheel_candidates.append((url, filename))

    if sdist_candidates:
        url, filename = sdist_candidates[-1]
        return (url, filename, "download")

    if pure_wheel_candidates:
        url, filename = pure_wheel_candidates[-1]
        return (url, filename, "download")

    if arch_skipped:
        url, filename = arch_skipped[-1]
        return (url, filename, "skip")

    return None


def fetch_package_page(pkg_name: str) -> str:
    for mirror in MIRROR_URLS:
        url = f"{mirror}/{pkg_name}/"
        buffer = BytesIO()
        curl = pycurl.Curl()
        curl.setopt(curl.URL, url)
        curl.setopt(curl.WRITEDATA, buffer)
        curl.setopt(curl.FOLLOWLOCATION, 1)
        curl.setopt(curl.TIMEOUT, TIMEOUT)
        curl.setopt(
            curl.USERAGENT,
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        curl.setopt(curl.ACCEPT_ENCODING, "gzip, deflate")
        curl.setopt(
            curl.HTTPHEADER,
            [
                "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language: en-US,en;q=0.5",
            ],
        )
        try:
            curl.perform()
            response_code = curl.getinfo(curl.RESPONSE_CODE)
            if response_code == 200:
                html = buffer.getvalue().decode("utf-8")
                if html.strip():
                    return html
                print(f"  Empty response from {mirror}, trying next...")
            else:
                if response_code == 404:
                    print(f"  Package '{pkg_name}' not found on {mirror}, trying next...")
                elif response_code == 403:
                    print(f"  HTTP 403: Forbidden on {mirror}, trying next...")
                elif response_code == 429:
                    print(f"  HTTP 429: Rate limited on {mirror}, trying next...")
                else:
                    print(f"  HTTP {response_code} from {mirror}, trying next...")
        except Exception as e:
            print(f"  Error contacting {mirror}: {e}, trying next...")
        finally:
            curl.close()
    return ""


def extract_latest_download_url(html: str, pkg_name: str) -> tuple[str, str, str] | None:
    try:
        soup = BeautifulSoup(html, "html.parser")
        all_links = soup.find_all("a", href=True)
        if not all_links:
            return None
        return select_best_url(all_links, pkg_name)
    except Exception as e:
        return None


def get_remote_size(url: str) -> int:
    curl = pycurl.Curl()
    curl.setopt(curl.URL, url)
    curl.setopt(curl.NOBODY, 1)
    curl.setopt(curl.FOLLOWLOCATION, 1)
    curl.setopt(curl.TIMEOUT, TIMEOUT)
    curl.setopt(
        curl.USERAGENT,
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    curl.setopt(curl.ACCEPT_ENCODING, "gzip, deflate")
    try:
        curl.perform()
        response_code = curl.getinfo(curl.RESPONSE_CODE)
        if response_code == 200:
            size = curl.getinfo(curl.CONTENT_LENGTH_DOWNLOAD)
            if size and size > 0:
                return int(size)
    except Exception:
        pass
    finally:
        curl.close()
    return -1


def download_file_with_retry(url: str, filename: str, max_retries: int = MAX_RETRIES) -> bool:
    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(RETRY_DELAY * attempt)
        if download_file(url, filename):
            return True
    return False


def download_file(url: str, filename: str) -> bool:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DOWNLOAD_DIR / filename
    if output_path.exists() and output_path.stat().st_size > 0:
        return True

    
    remote_size = get_remote_size(url)
    if remote_size > 0:
        print(f"  Size: {human_size(remote_size)} ({remote_size:,} bytes)")
    else:
        print("  Size: unknown")

    print(f"  Downloading: {filename}")
    with open(output_path, "wb") as f:
        curl = pycurl.Curl()
        curl.setopt(curl.URL, url)
        curl.setopt(curl.WRITEDATA, f)
        curl.setopt(curl.FOLLOWLOCATION, 1)
        curl.setopt(curl.TIMEOUT, 120)
        curl.setopt(
            curl.USERAGENT,
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        curl.setopt(curl.ACCEPT_ENCODING, "gzip, deflate")
        curl.setopt(
            curl.HTTPHEADER,
            [
                "Accept: */*",
                "Accept-Language: en-US,en;q=0.5",
            ],
        )
        curl.setopt(curl.NOPROGRESS, 0)

        def progress_callback(download_t, download_d, upload_t, upload_d):
            if download_t > 0:
                percent = (download_d * 40) / download_t
                if int(percent) % 10 == 0:
                    cprint(
                        f"  Progress: {percent:.1f}% ({human_size(download_d)}/{human_size(download_t)})",
                        end="\r",
                    )
            else:
                cprint(f"  Downloaded: {human_size(download_d)}", end="\r")
            return 0

        curl.setopt(curl.XFERINFOFUNCTION, progress_callback)
        try:
            curl.perform()
            response_code = curl.getinfo(curl.RESPONSE_CODE)
            if response_code == 200:
                print()
                file_size = output_path.stat().st_size
                return True
            else:
                if response_code == 403:
                    print("  HTTP 403: Forbidden - Access denied")
                elif response_code == 404:
                    print("  HTTP 404: File not found on mirror")
                elif response_code == 429:
                    print("  HTTP 429: Too Many Requests - Rate limited, try again later")
                if output_path.exists():
                    output_path.unlink()
                return False
        except Exception as e:
            if output_path.exists():
                output_path.unlink()
            return False
        finally:
            curl.close()


def process_package(pkg_name: str) -> tuple[bool, bool]:
    html = fetch_package_page(pkg_name)
    if not html:
        return (False, False)
    download_info = extract_latest_download_url(html, pkg_name)
    if not download_info:
        return (False, False)

    url, filename, status = download_info

    if status == "skip":
        return (True, True)

    print(f"Download URL: {url}")
    ok = download_file_with_retry(url, filename)
    return (ok, False)


def main():
    packages = sys.argv[1:]
    start_time = time.time()
    successful = []
    failed = []
    skipped = []
    for pkg_name in packages:
        try:
            ok, was_skipped = process_package(pkg_name)
            if was_skipped:
                skipped.append(pkg_name)
            elif ok:
                successful.append(pkg_name)
            else:
                failed.append(pkg_name)
        except Exception as e:
            failed.append(pkg_name)
    if successful:
        print(f"\nSuccessfully downloaded:")
        for pkg in successful:
            print(f"  ✓ {pkg}")
    if skipped:
        print(f"\nSkipped (arch-specific, no pure source/wheel available):")
        for pkg in skipped:
            print(f"  ⚠ {pkg}")
    if failed:
        print(f"\nFailed to download:")
        for pkg in failed:
            print(f"  ✗ {pkg}")


if __name__ == "__main__":
    main()
