import base64
import mimetypes
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from multiprocessing import Pool
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup

mimetypes.add_type("application/font-woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("application/vnd.ms-fontobject", ".eot")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/json", ".json")

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; StandaloneHTML/1.0)"})

REMOTE_FILE_SIZE_LIMIT = 5 * 1024 * 1024  


_confirmed_urls = {}


def guess_mime(url, content_type=None):
    if content_type:
        ct = content_type.split(";")[0].strip()
        if ct:
            return ct
    path = urlparse(url).path
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def is_remote_url(url: str) -> bool:
    return url.startswith(("http://", "https://", "//"))


def check_remote_file_size(url: str) -> Optional[int]:
    try:
        resp = session.head(url, timeout=10, allow_redirects=True)
        content_length = resp.headers.get("Content-Length")
        if content_length:
            return int(content_length)
    except Exception as e:
        pass  
    return None


def ask_user_confirmation(url: str, size_mb: float) -> bool:
    if url in _confirmed_urls:
        return _confirmed_urls[url]

    response = input(f"\n⚠ ALERT: Download {size_mb:.2f}MB file?\n   URL: {url}\n   Proceed? (y/n): ").strip().lower()

    confirmed = response in ("y", "yes")
    _confirmed_urls[url] = confirmed
    return confirmed


def fetch(url, base_dir):
    if not url or url.startswith("data:"):
        return None, None

    if url.startswith("//"):
        url = "https:" + url

    if is_remote_url(url):
        
        path = urlparse(url).path.lower()
        if any(
            path.endswith(ext)
            for ext in [
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".webp",
                ".svg",
                ".bmp",
                ".ico",
            ]
        ):
            print(f"  ⊘ skipped remote image: {url}")
            return None, None

        
        file_size = check_remote_file_size(url)
        if file_size and file_size > REMOTE_FILE_SIZE_LIMIT:
            size_mb = file_size / (1024 * 1024)

            
            if not ask_user_confirmation(url, size_mb):
                print(f"  ⊘ skipped (user declined): {url}")
                return None, None

        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            mime = guess_mime(url, resp.headers.get("Content-Type"))
            print(f"  ↓ downloaded: {url}")
            return resp.content, mime
        except Exception as e:
            print(f"  ⚠ failed to download {url}: {e}")
            return None, None
    else:
        clean = url.split("?")[0].split("#")[0]
        local_path = Path(base_dir) / clean
        local_path = local_path.resolve()

        if local_path.is_file():
            try:
                content = local_path.read_bytes()
                mime = guess_mime(url)
                print(f"  ⏵ inlined local: {url}")
                return content, mime
            except Exception as e:
                print(f"  ⚠ failed to read {local_path}: {e}")
                return None, None
        else:
            print(f"  ⚠ file not found: {local_path}")
            return None, None


def to_data_uri(content, mime):
    b64 = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _css_base_for(css_source, fallback_base):
    if not css_source or css_source.startswith("data:"):
        return fallback_base
    if is_remote_url(css_source):
        return css_source.rsplit("/", 1)[0] + "/"
    return str(Path(css_source).parent or Path("."))


def process_css(css_text, base_dir, css_source=None):
    css_base = _css_base_for(css_source, fallback_base=base_dir)

    def replace_import(match):
        full = match.group(0)
        import_url = match.group(1).strip().strip("\"'")
        if import_url.startswith("data:"):
            return full
        content, _mime = fetch(import_url, css_base)
        if content is None:
            return full
        try:
            imported = content.decode("utf-8", errors="replace")
        except Exception:
            return full
        return process_css(imported, css_base, import_url)

    css_text = re.sub(
        r'@import\s+(?:url\(\s*)?["\']?([^"\')\s]+)["\']?\s*\)?[^;]*;',
        replace_import,
        css_text,
    )

    def replace_url(match):
        full = match.group(0)
        url = match.group(1).strip()
        if url.startswith("data:") or url.startswith("#"):
            return full
        content, mime = fetch(url, css_base)
        if content is None:
            return full
        return f'url("{to_data_uri(content, mime)}")'

    css_text = re.sub(
        r'url\(\s*["\']?([^"\')]+)["\']?\s*\)',
        replace_url,
        css_text,
    )
    return css_text


def process_srcset(srcset, base_dir):
    parts = []
    for item in srcset.split(","):
        item = item.strip()
        if not item:
            continue
        tokens = item.split()
        url = tokens[0]
        descriptor = " ".join(tokens[1:]) if len(tokens) > 1 else ""
        if url.startswith("data:"):
            parts.append(item)
            continue
        content, mime = fetch(url, base_dir)
        if content is not None:
            uri = to_data_uri(content, mime)
            parts.append(f"{uri} {descriptor}" if descriptor else uri)
        else:
            parts.append(item)
    return ", ".join(parts)


def make_standalone(html_path):
    html_path = Path(html_path).resolve()
    base_dir = html_path.parent

    if not html_path.is_file():
        print(f"ERROR: file not found: {html_path}")
        return False

    print(f"Processing: {html_path}\n")

    try:
        html_content = html_path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception as e:
        print(f"ERROR: failed to read {html_path}: {e}")
        return False

    soup = BeautifulSoup(html_content, "html.parser")

    
    for link in soup.find_all("link", rel=True):
        rels = link.get("rel", [])
        if isinstance(rels, str):
            rels = [rels]
        if "stylesheet" not in [r.lower() for r in rels]:
            continue
        href = link.get("href")
        if not href or href.startswith("data:"):
            continue
        content, _ = fetch(href, base_dir)
        if content is None:
            continue
        css_text = content.decode("utf-8", errors="replace")
        css_text = process_css(css_text, base_dir, href)
        style_tag = soup.new_tag("style")
        style_tag.string = css_text
        link.replace_with(style_tag)

    
    for link in soup.find_all("link", href=True):
        rels = link.get("rel", [])
        if isinstance(rels, str):
            rels = [rels]
        if "stylesheet" in [r.lower() for r in rels]:
            continue
        if any(r.lower() == "manifest" for r in rels):
            continue
        href = link.get("href")
        if not href or href.startswith("data:"):
            continue
        content, mime = fetch(href, base_dir)
        if content is not None:
            link["href"] = to_data_uri(content, mime)

    
    for script in soup.find_all("script", src=True):
        src = script.get("src")
        if not src or src.startswith("data:"):
            continue
        content, _ = fetch(src, base_dir)
        if content is None:
            continue
        js_text = content.decode("utf-8", errors="replace")
        js_text = re.sub(r"\n?//#\s*sourceMappingURL=.*", "", js_text)
        js_text = re.sub(r"</script", r"<\\/script", js_text, flags=re.IGNORECASE)
        del script["src"]
        script.string = js_text

    
    for img in soup.find_all("img", src=True):
        src = img.get("src")
        if not src or src.startswith("data:"):
            continue
        if is_remote_url(src):
            print(f"  ⊘ skipped remote image: {src}")
            continue
        content, mime = fetch(src, base_dir)
        if content is not None:
            img["src"] = to_data_uri(content, mime)

    
    for tag in soup.find_all(srcset=True):
        tag["srcset"] = process_srcset(tag["srcset"], base_dir)

    
    for source in soup.find_all("source", src=True):
        src = source.get("src")
        if not src or src.startswith("data:"):
            continue
        content, mime = fetch(src, base_dir)
        if content is not None:
            source["src"] = to_data_uri(content, mime)

    
    for video in soup.find_all("video", poster=True):
        poster = video.get("poster")
        if not poster or poster.startswith("data:"):
            continue
        content, mime = fetch(poster, base_dir)
        if content is not None:
            video["poster"] = to_data_uri(content, mime)

    
    for tag in soup.find_all(["audio", "video"], src=True):
        src = tag.get("src")
        if not src or src.startswith("data:"):
            continue
        content, mime = fetch(src, base_dir)
        if content is not None:
            tag["src"] = to_data_uri(content, mime)

    
    for obj in soup.find_all("object", data=True):
        data = obj.get("data")
        if not data or data.startswith("data:"):
            continue
        content, mime = fetch(data, base_dir)
        if content is not None:
            obj["data"] = to_data_uri(content, mime)

    
    for embed in soup.find_all("embed", src=True):
        src = embed.get("src")
        if not src or src.startswith("data:"):
            continue
        content, mime = fetch(src, base_dir)
        if content is not None:
            embed["src"] = to_data_uri(content, mime)

    
    for inp in soup.find_all("input", src=True):
        src = inp.get("src")
        if not src or src.startswith("data:"):
            continue
        content, mime = fetch(src, base_dir)
        if content is not None:
            inp["src"] = to_data_uri(content, mime)

    
    for track in soup.find_all("track", src=True):
        src = track.get("src")
        if not src or src.startswith("data:"):
            continue
        content, mime = fetch(src, base_dir)
        if content is not None:
            track["src"] = to_data_uri(content, mime)

    
    for style in soup.find_all("style"):
        css = style.string
        if not css:
            css = style.get_text()
        if css:
            css = re.sub(r"^\s*<!--\s*", "", css)
            css = re.sub(r"\s*-->\s*$", "", css)
            style.string = process_css(css, base_dir)

    for tag in soup.find_all(style=True):
        val = tag.get("style", "")
        if val:
            tag["style"] = process_css(val, base_dir)

    result = str(soup)
    try:
        html_path.write_text(result, encoding="utf-8")
        print(f"\n✓ Done — standalone HTML saved to: {html_path}")
        return True
    except Exception as e:
        print(f"ERROR: failed to write {html_path}: {e}")
        return False


def find_html_files(paths: list) -> list:
    if not paths:
        paths = ["."]

    html_files = []
    for path_str in paths:
        path = Path(path_str).resolve()
        if path.is_file() and path.suffix.lower() == ".html":
            html_files.append(str(path))
        elif path.is_dir():
            html_files.extend(str(p) for p in path.rglob("*.html"))

    return html_files


def main():
    input_paths = sys.argv[1:] if len(sys.argv) > 1 else []
    html_files = find_html_files(input_paths)

    if not html_files:
        print("No HTML files found.")
        sys.exit(1)

    print(f"Found {len(html_files)} HTML file(s) to process.\n")

    
    
    with Pool(8) as pool:
        results = pool.map(make_standalone, html_files)

    success_count = sum(1 for r in results if r)
    print(f"\n{'=' * 50}")
    print(f"Processed {success_count}/{len(html_files)} files successfully.")


if __name__ == "__main__":
    main()
