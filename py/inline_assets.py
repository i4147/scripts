from __future__ import annotations

import argparse
import base64
import mimetypes
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="WARNING", format="<red>{level}</red> | <cyan>{message}</cyan>")
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".avif",
    ".bmp",
    ".tiff",
}
CSS_URL_PATTERN = re.compile(r'url\((["\']?)([^)"\']+)\1\)')
TIMEOUT = 15


def is_remote(url: str) -> bool:
    return urlparse(url).scheme in ("http", "https") or url.startswith("//")


def is_image(url: str) -> bool:
    ext = Path(urlparse(url).path).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def get_mime_type(file_path: str) -> str:
    mime, _ = mimetypes.guess_type(file_path)
    if not mime:
        ext = Path(file_path).suffix.lower()
        if ext == ".woff2":
            return "font/woff2"
        if ext == ".woff":
            return "font/woff"
        if ext == ".ttf":
            return "font/ttf"
        if ext == ".eot":
            return "application/vnd.ms-fontobject"
        return "application/octet-stream"
    return mime


def fetch_remote(url: str) -> bytes | None:
    if url.startswith("//"):
        url = "https:" + url
    try:
        with requests.get(url, timeout=TIMEOUT) as response:
            response.raise_for_status()
            return response.content
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def read_local(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except Exception as e:
        logger.error(f"Failed to read {path}: {e}")
        return None


def process_css_content(css_content: str, base_path: Path, base_url: str | None = None) -> tuple[str, int, int]:
    loc, rem = 0, 0

    def replacer(match: re.Match) -> str:
        nonlocal loc, rem
        quote = match.group(1)
        url = match.group(2)
        if url.startswith("data:"):
            return match.group(0)
        if is_remote(url):
            if is_image(url):
                return match.group(0)
            target_url = urljoin(base_url, url) if base_url else url
            content = fetch_remote(target_url)
            if content:
                mime = get_mime_type(urlparse(target_url).path)
                b64 = base64.b64encode(content).decode("ascii")
                rem += 1
                return f"url({quote}data:{mime};base64,{b64}{quote})"
            return match.group(0)
        else:
            clean_url = url.split("?")[0].split("#")[0]
            local_file = (base_path.parent / clean_url).resolve()
            if not local_file.exists():
                logger.warning(f"Missing local CSS asset referenced: {local_file}")
                return match.group(0)
            content = read_local(local_file)
            if content:
                mime = get_mime_type(str(local_file))
                b64 = base64.b64encode(content).decode("ascii")
                loc += 1
                return f"url({quote}data:{mime};base64,{b64}{quote})"
            return match.group(0)

    new_css = CSS_URL_PATTERN.sub(replacer, css_content)
    return new_css, loc, rem


def process_html_file(file_path: Path) -> dict:
    stats = {
        "path": str(file_path),
        "local": 0,
        "remote": 0,
        "time": 0.0,
        "status": "success",
    }
    start = time.perf_counter()
    try:
        html_text = file_path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html_text, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src or src.startswith("data:"):
                continue
            if is_remote(src):
                continue
            clean_src = src.split("?")[0].split("#")[0]
            local_img_path = (file_path.parent / clean_src).resolve()
            if local_img_path.exists():
                if content := read_local(local_img_path):
                    b64 = base64.b64encode(content).decode("ascii")
                    mime = get_mime_type(str(local_img_path))
                    img["src"] = f"data:{mime};base64,{b64}"
                    stats["local"] += 1
            else:
                logger.warning(f"Missing local image: {local_img_path} in {file_path}")
        for link in soup.find_all("link", rel="stylesheet"):
            href = link.get("href")
            if not href:
                continue
            css_text, base_url, css_base_path = "", None, file_path
            if is_remote(href):
                if raw := fetch_remote(href):
                    css_text = raw.decode("utf-8", errors="ignore")
                    base_url = href
                    stats["remote"] += 1
            else:
                clean_href = href.split("?")[0].split("#")[0]
                local_css_path = (file_path.parent / clean_href).resolve()
                if local_css_path.exists():
                    css_text = local_css_path.read_text(encoding="utf-8", errors="ignore")
                    css_base_path = local_css_path
                    stats["local"] += 1
                else:
                    logger.warning(f"Missing local CSS: {local_css_path} in {file_path}")
            if css_text:
                processed_css, c_loc, c_rem = process_css_content(css_text, css_base_path, base_url)
                stats["local"] += c_loc
                stats["remote"] += c_rem
                style_tag = soup.new_tag("style")
                style_tag.string = processed_css
                link.replace_with(style_tag)
        for script in soup.find_all("script"):
            src = script.get("src")
            if not src:
                continue
            script_text = ""
            if is_remote(src):
                if raw := fetch_remote(src):
                    script_text = raw.decode("utf-8", errors="ignore")
                    stats["remote"] += 1
            else:
                clean_src = src.split("?")[0].split("#")[0]
                local_script = (file_path.parent / clean_src).resolve()
                if local_script.exists():
                    script_text = local_script.read_text(encoding="utf-8", errors="ignore")
                    stats["local"] += 1
                else:
                    logger.warning(f"Missing local script: {local_script} in {file_path}")
            if script_text:
                new_script = soup.new_tag("script")
                new_script.string = script_text
                script.replace_with(new_script)
        for tag in soup.find_all(style=True):
            processed, l, r = process_css_content(tag["style"], file_path)
            tag["style"] = processed
            stats["local"] += l
            stats["remote"] += r
        for style in soup.find_all("style"):
            if style.string:
                processed, l, r = process_css_content(style.string, file_path)
                style.string = processed
                stats["local"] += l
                stats["remote"] += r
        file_path.write_text(str(soup), encoding="utf-8")
    except Exception as e:
        stats["status"] = f"error: {e}"
        logger.error(f"Failed to process HTML file {file_path}: {e}")
    stats["time"] = time.perf_counter() - start
    return stats


def process_css_file(file_path: Path) -> dict:
    stats = {
        "path": str(file_path),
        "local": 0,
        "remote": 0,
        "time": 0.0,
        "status": "success",
    }
    start = time.perf_counter()
    try:
        content = file_path.read_text(encoding="utf-8")
        processed_css, l, r = process_css_content(content, file_path)
        stats["local"] += l
        stats["remote"] += r
        file_path.write_text(processed_css, encoding="utf-8")
    except Exception as e:
        stats["status"] = f"error: {e}"
        logger.error(f"Failed to process CSS file {file_path}: {e}")
    stats["time"] = time.perf_counter() - start
    return stats


def process_file(path: Path) -> dict:
    if path.suffix.lower() == ".html":
        return process_html_file(path)
    elif path.suffix.lower() == ".css":
        return process_css_file(path)
    return {
        "path": str(path),
        "local": 0,
        "remote": 0,
        "time": 0.0,
        "status": "skipped",
    }


def main():
    parser = argparse.ArgumentParser(description="Standalone HTML/CSS Bundler Tool")
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to process (default: current directory)",
    )
    args = parser.parse_args()
    targets: list[Path] = []
    for p_str in args.paths:
        p = Path(p_str)
        if p.is_file() and p.suffix.lower() in (".html", ".css"):
            targets.append(p)
        elif p.is_dir():
            targets.extend(p.rglob("*.html"))
            targets.extend(p.rglob("*.css"))
    targets = list({p.resolve(): p for p in targets}.values())
    if not targets:
        print("\033[93mNo HTML or CSS files found to process.\033[0m")
        return
    print(f"\033[96mProcessing {len(targets)} files across multiple CPU cores...\033[0m\n")
    t_loc, t_rem = 0, 0
    start_time = time.perf_counter()
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(process_file, p): p for p in targets}
        for future in as_completed(futures):
            s = future.result()
            raw_path = Path(s["path"])
            try:
                display_path = raw_path.relative_to(Path.cwd())
            except ValueError:
                display_path = raw_path
            t_loc += s["local"]
            t_rem += s["remote"]
            status = s["status"]
            if status == "success":
                print(
                    f"\033[92m[SUCCESS]\033[0m "
                    f"\033[96m{display_path}\033[0m "
                    f"({s['time']:.2f}s) - Embedded: "
                    f"\033[93m{s['local']} local\033[0m, "
                    f"\033[93m{s['remote']} remote\033[0m"
                )
            elif status == "skipped":
                pass
            else:
                print(f"\033[91m[ERROR]\033[0m {display_path} - {status}")
    total_time = time.perf_counter() - start_time
    print(f"\n\033[1;92mBuild Complete in {total_time:.2f}s!\033[0m")
    print(f"Total globally embedded resources: \033[93m{t_loc}\033[0m local, \033[93m{t_rem}\033[0m remote.")


if __name__ == "__main__":
    main()
