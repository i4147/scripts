import contextlib
import html as _html
import re
import sys
import urllib.parse
from pathlib import Path

import requests
from dh import cprint
from packaging.version import Version


def save_output(content: str, pkg) -> None:
    Path(f"/sdcard/whl/json/{pkg}").write_text(content, encoding="utf-8")


def parse_version_obj(s) -> Version:
    return Version(s)


def extract_links(html_text):
    pattern = re.compile("<a\\s+[^>]*href=([\"\\'])(?P<href>.*?)\\1[^>]*>(?P<text>.*?)</a>", re.IGNORECASE | re.DOTALL)
    for m in pattern.finditer(html_text):
        href = _html.unescape(m.group("href")).strip()
        text = _html.unescape(re.sub("<[^>]+>", "", m.group("text"))).strip()
        yield (href, text)


def filename_from_href(href: str):
    p = urllib.parse.urlparse(href)
    name = Path(p.path).name
    if not name:
        frag = p.fragment
        name = frag or p.netloc
    return name


def find_version_in_text(s):
    m = re.search("(?<![\\d.])(\\d+(?:\\.\\d+)+)(?![\\d.])", s)
    return m.group(1) if m else None


def ext_priority(fname) -> int:
    f = fname.lower()
    if f.endswith(".whl"):
        return 0
    if f.endswith((".tar.gz", ".tgz")):
        return 1
    if f.endswith((".zip", ".tar.bz2")):
        return 2
    return 3


def extract_latest_version_link(html_text):
    entries = []
    rev_html = html_text[::-1]
    target_line = ""
    for k in rev_html:
        if "<a href" in k:
            print(k)
            target_line = k
            break
    for href, text in extract_links(html_text):
        href = href.split('"')[0].split("'")[0]
        fname = filename_from_href(href) or text
        ver = find_version_in_text(fname) or find_version_in_text(text)
        if not ver:
            continue
        try:
            ver_obj = parse_version_obj(ver)
        except Exception:
            ver_obj = ver
        pr = ext_priority(fname)
        entries.append((ver_obj, pr, href, fname))
    if not entries:
        print("no versioned links found", file=sys.stderr)
        sys.exit(1)
    best = max(entries, key=lambda e: (e[0], -e[1]))
    return best[2]


def get_latest_pkg_version(pkg_name: str):
    try:
        url = f"https://mirror-pypi.runflare.com/{pkg_name}/json"
        html = requests.get(url, timeout=50).text
        save_output(html, pkg_name)
    except:
        return None
    wheel_pattern = re.compile(
        f"{re.escape(pkg_name)}-([0-9][A-Za-z0-9\\.\\-_]*)\\.(?:whl|tar\\.gz|zip)", re.IGNORECASE
    )
    versions = []
    for match in wheel_pattern.finditer(html):
        version_str = match.group(1)
        with contextlib.suppress(BaseException):
            versions.append(Version(version_str))
    latest_version_link = get_latest_pkg_version(html)
    if latest_version_link:
        with Path("/sdcard/pkgs_links").open("a", encoding="utf-8") as f:
            f.write(f"\n{latest_version_link}\n")
    return max(versions) if versions else None


if __name__ == "__main__":
    try:
        pkg = sys.argv[1]
        latest_version = get_latest_pkg_version(pkg)
        cprint(f"{pkg} : ", "green", end=" | ")
        cprint(f"{latest_version}", "cyan")
    except:
        pass
