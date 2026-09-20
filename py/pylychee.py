from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, urldefrag

EXT_IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}
HTTP_SCHEMES = ("http://", "https://")
HTML_ATTR_RE = re.compile(r'(?P<attr>href|src)\s*=\s*(?P<q>["\'])(?P<url>.*?)(?P=q)', re.IGNORECASE)
MD_IMAGE_RE = re.compile(r"!\[([^\]]*?)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]*?)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
SPLIT_URL_RE = re.compile(r"^(?P<path>[^?#]+)(?P<rest>[?#].*)?$")
DEFAULT_TIMEOUT = 8
MAX_WORKERS = 32


def _strip_fragment_query(u: str) -> str:
    v, _ = urldefrag(u)
    if "?" in v:
        v = v.split("?", 1)[0]
    return v


def _guess_ext(u: str) -> str:
    p = _strip_fragment_query(u)
    _, ext = os.path.splitext(p.lower())
    return ext


def _is_remote(u: str) -> bool:
    s = u.strip()
    return any(s.startswith(x) for x in HTTP_SCHEMES)


def _is_local_ref(u: str) -> bool:
    s = u.strip()
    if not s:
        return False
    if s.startswith("#"):
        return False
    return not _is_remote(s)


def _is_imageish(u: str) -> bool:
    ext = _guess_ext(u)
    return ext in EXT_IMAGE or ext == ".svg"


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _local_target_resolve(base_dir: str, u: str) -> str | None:
    s = u.strip()
    if not s:
        return None
    if s.startswith("/"):
        return None
    if "#" in s or "?" in s:
        s = _strip_fragment_query(s)
    s = unquote(s)
    norm = os.path.normpath(os.path.join(base_dir, s))
    if not os.path.abspath(norm).startswith(os.path.abspath(base_dir).rsplit(os.sep, 1)[0]):
        return os.path.abspath(norm)
    return os.path.abspath(norm)


def _mime_for_local(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".svg":
        return "image/svg+xml"
    m, _ = mimetypes.guess_type(path)
    return m or "application/octet-stream"


def _to_data_uri(path: str) -> str:
    mime = _mime_for_local(path)
    raw = _read_bytes(path)
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _http_check(url: str, timeout: int) -> bool:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
            return code < 400
    except Exception:
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = getattr(resp, "status", 200)
                return code < 400
        except Exception:
            return False


def _replace_html(html: str, file_dir: str, timeout: int) -> tuple[str, list[str]]:
    removals = []
    changes = 0

    def html_attr_repl(m: re.Match) -> str:
        nonlocal changes
        attr = m.group("attr")
        q = m.group("q")
        url = m.group("url")
        raw = url
        target = url.strip()
        if not target or target.startswith(("#", "data:")):
            return m.group(0)
        if _is_remote(target):
            if _is_imageish(target):
                ok = _http_check(target, timeout)
                if not ok:
                    removals.append(f"REMOTE_UNAVAILABLE_IMAGE {attr}={raw}")
                    changes += 1
                    return f"{attr}={q}{q}"
                return m.group(0)
            return m.group(0)
        if _is_local_ref(target):
            local_path = _local_target_resolve(file_dir, target)
            if not local_path or not os.path.isfile(local_path):
                removals.append(f"LOCAL_UNAVAILABLE {attr}={raw}")
                return m.group(0)
            if _is_imageish(target):
                try:
                    data_uri = _to_data_uri(local_path)
                except Exception:
                    removals.append(f"LOCAL_INLINE_FAILED {attr}={raw}")
                    return m.group(0)
                changes += 1
                return f"{attr}={q}{data_uri}{q}"
        return m.group(0)

    out = HTML_ATTR_RE.sub(html_attr_repl, html)
    return out, removals


def _replace_md(md: str, file_dir: str, timeout: int) -> tuple[str, list[str]]:
    removals = []
    changes = 0

    def replace_md_images(match: re.Match) -> str:
        nonlocal changes
        url = match.group("url").strip()
        if not url or url.startswith(("#", "data:")):
            return match.group(0)
        if _is_remote(url):
            if _is_imageish(url):
                ok = _http_check(url, timeout)
                if not ok:
                    removals.append(f"REMOTE_UNAVAILABLE_IMAGE_MD {url}")
                    changes += 1
                    return "" if url.endswith(".svg") else ""
            return match.group(0)
        if _is_local_ref(url) and _is_imageish(url):
            local_path = _local_target_resolve(file_dir, url)
            if not local_path or not os.path.isfile(local_path):
                removals.append(f"LOCAL_UNAVAILABLE_MD {url}")
                return match.group(0)
            try:
                data_uri = _to_data_uri(local_path)
            except Exception:
                removals.append(f"LOCAL_INLINE_FAILED_MD {url}")
                return match.group(0)
            changes += 1
            text = match.group(1) or ""
            return f"![{text}]({data_uri})"
        return match.group(0)

    def replace_md_links(match: re.Match) -> str:
        url = match.group("url").strip()
        if not url or url.startswith(("#", "data:")):
            return match.group(0)
        if _is_remote(url):
            ext = _guess_ext(url)
            if ext == ".svg" or ext in EXT_IMAGE:
                ok = _http_check(url, timeout)
                if not ok:
                    removals.append(f"REMOTE_UNAVAILABLE_IMAGE_MD_LINK {url}")
                    return match.group(0).replace(f"({url})", "()")
            return match.group(0)
        if _is_local_ref(url):
            local_path = _local_target_resolve(file_dir, url)
            if not local_path or not os.path.isfile(local_path):
                removals.append(f"LOCAL_UNAVAILABLE_MD_LINK {url}")
            return match.group(0)
        return match.group(0)

    out = MD_IMAGE_RE.sub(replace_md_images, md)
    out = MD_LINK_RE.sub(replace_md_links, out)
    return out, removals


def process_file(path: str, timeout: int) -> list[str]:
    file_dir = os.path.dirname(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    changed = False
    report = []
    if path.lower().endswith(".html") or path.lower().endswith(".htm"):
        new_content, report = _replace_html(content, file_dir, timeout)
        changed = new_content != content
    elif path.lower().endswith(".md"):
        new_content, report = _replace_md(content, file_dir, timeout)
        changed = new_content != content
    else:
        return []
    if changed:
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(new_content)
    return report


def iter_files(root: str, exts: tuple[str, ...]) -> list[str]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.lower().endswith(exts):
                out.append(os.path.join(dirpath, fn))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", help="Folder to scan")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = p.parse_args()
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print("root is not a directory", file=sys.stderr)
        sys.exit(2)
    files = iter_files(root, (".md", ".html", ".htm"))
    if not files:
        return
    all_reports = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(process_file, fp, args.timeout): fp for fp in files}
        for fut in as_completed(futs):
            fp = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                all_reports.append(f"FAILED {fp} {e}")
                continue
            all_reports.extend(r)
    if all_reports:
        for line in all_reports:
            print(line)


if __name__ == "__main__":
    raise SystemExit(main())
