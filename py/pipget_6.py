import argparse
import re
import sys
import time
from io import BytesIO
from pathlib import Path

import pycurl
from bs4 import BeautifulSoup
from dh import cprint

# Mirror configurations
MIRRORS = {
    "runflare": "https://mirror-pypi.runflare.com",
    "pypi": "https://pypi.org/simple",
    "tsinghua": "https://pypi.tuna.tsinghua.edu.cn/simple",
}
DEFAULT_MIRROR = "runflare"

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


def is_windows_url(url: str) -> bool:
    """Check if URL is a Windows-tagged package."""
    lower = url.lower()
    return (
        "win32" in lower
        or "win_amd64" in lower
        or "win_arm64" in lower
        or "-win-" in lower
    )


def has_arch_tag(url: str) -> bool:
    """Check if URL has any architecture/platform specific tag."""
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
    """Check if URL points to a source distribution (.tar.gz)."""
    return url.lower().endswith(".tar.gz")


def is_pure_wheel(url: str) -> bool:
    """Check if URL is a pure Python wheel (py3-none-any)."""
    lower = url.lower()
    if not lower.endswith(".whl"):
        return False
    return "py3-none-any" in lower or "py2.py3-none-any" in lower


def select_best_url(links: list, pkg_name: str) -> tuple[str, str, str] | None:
    """
    Select best download URL from links.
    Returns (url, filename, status) where status is:
      - "download" : should be downloaded
      - "skip"     : has arch tag, should be skipped but URL reported
      - "error"    : no suitable file found
    """
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


def find_existing_package(pkg_name: str) -> bool:
    """Check if any file for this package already exists in the download dir."""
    normalized = pkg_name.lower().replace("-", "_").replace(".", "_")
    pattern = re.compile(
        r"^" + re.escape(normalized) + r"[-_.]v?\d",
        re.IGNORECASE,
    )

    for f in DOWNLOAD_DIR.iterdir():
        if not f.is_file() or f.stat().st_size == 0:
            continue
        fname = f.name.lower().replace("-", "_")
        if pattern.match(fname):
            return True
    return False


def fetch_package_page(pkg_name: str, mirror_base: str, is_simple_index: bool) -> str:
    """
    Fetch the package page from the given mirror.

    - For 'simple index' style mirrors (PyPI, Tsinghua), the URL is
      {base}/{name}/  and the page contains direct links to files.
    - For the runflare mirror, the URL is {base}/{name} (no trailing slash).
    """
    if is_simple_index:
        url = f"{mirror_base.rstrip('/')}/{pkg_name}/"
    else:
        url = f"{mirror_base.rstrip('/')}/{pkg_name}"

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
        if response_code != 200:
            if response_code == 402:
                print(
                    "  HTTP 402: Payment Required - The mirror might require authentication"
                )
            elif response_code == 403:
                print("  HTTP 403: Forbidden - Access denied")
            elif response_code == 404:
                print(f"  Package '{pkg_name}' not found on mirror")
            elif response_code == 429:
                print("  HTTP 429: Too Many Requests - Rate limited")
            return ""
        return buffer.getvalue().decode("utf-8", errors="replace")
    except Exception:
        return ""
    finally:
        curl.close()


def extract_latest_download_url(
    html: str, pkg_name: str
) -> tuple[str, str, str] | None:
    try:
        soup = BeautifulSoup(html, "html.parser")
        all_links = soup.find_all("a", href=True)
        if not all_links:
            return None
        return select_best_url(all_links, pkg_name)
    except Exception:
        return None


def download_file