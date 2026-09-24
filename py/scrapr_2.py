import argparse
import json
import re
import signal
from multiprocessing import Manager, Pool
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from loguru import logger

DEFAULT_URL = "https://sr.moviesho.com/Series/"
STATE_FILE = Path("crawler_state.json")
TXT_OUTPUT = Path("movies.txt")
JSON_OUTPUT = Path("movies.json")
FIXED_WORKERS = 8
stop_flag = False


def signal_handler(sig, frame):
    global stop_flag
    logger.warning("⚠️  Interrupt received! Saving progress...")
    stop_flag = True


signal.signal(signal.SIGINT, signal_handler)


def size_to_mb(size_str):
    match = re.search(r"([\d.]+)\s*Mi?B", size_str)
    if match:
        return float(match.group(1))
    return None


def extract_quality(filename):
    lower = filename.lower()
    if "480p" in lower:
        return "480"
    if "720p" in lower:
        return "720"
    return None


def fetch_directory(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception as exc:
        logger.debug(f"Failed to fetch {url}: {exc}")
        return None


def parse_directory(url, max_size):
    results = []
    subdirs = []
    html = fetch_directory(url)
    if not html:
        return results, subdirs
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue
        link_tag = cols[0].find("a")
        if not link_tag:
            continue
        name = link_tag.text.strip()
        href = link_tag.get("href")
        if not href:
            continue
        size_text = cols[1].text.strip()
        if "Parent directory" in name:
            continue
        full_url = urljoin(url, href)
        if href.endswith("/"):
            subdirs.append(full_url)
            continue
        if not name.lower().endswith(".mkv"):
            continue
        quality = extract_quality(name)
        if quality not in ("480", "720"):
            continue
        size_mb = size_to_mb(size_text)
        if size_mb is None or size_mb > max_size:
            continue
        results.append({"url": full_url, "quality": quality, "size_mb": size_mb})
    return results, subdirs


def save_state(queue, visited):
    state = {"queue": list(queue), "visited": list(visited)}
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f)


def load_state():
    if not STATE_FILE.exists():
        return None, None
    with STATE_FILE.open(encoding="utf-8") as f:
        state = json.load(f)
    return set(state["visited"]), state["queue"]


def append_results(results):
    with TXT_OUTPUT.open("a", encoding="utf-8") as f:
        f.writelines(r["url"] + "\n" for r in results)
    with JSON_OUTPUT.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in results)


def main():
    global stop_flag
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--url", default=DEFAULT_URL, help="Base URL to crawl")
    parser.add_argument("-s", "--size", type=float, default=300, help="Max size in MB (default 300)")
    args = parser.parse_args()
    max_size = args.size
    base_url = args.url if args.url.endswith("/") else args.url + "/"
    manager = Manager()
    visited = manager.list()
    queue = manager.list()
    prev_visited, prev_queue = load_state()
    if prev_queue:
        print("🔁 Resuming previous crawl...")
        visited[:] = prev_visited or []
        queue[:] = prev_queue
    else:
        queue.append(base_url)
    print(f"🚀 Using {FIXED_WORKERS} processes")
    with Pool(processes=FIXED_WORKERS) as pool:
        while queue and not stop_flag:
            in_flight = []
            for _ in range(min(len(queue), FIXED_WORKERS)):
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.append(url)
                async_result = pool.apply_async(parse_directory, (url, max_size))
                in_flight.append((async_result, url))
            for async_result, _ in in_flight:
                if stop_flag:
                    break
                try:
                    results, subdirs = async_result.get()
                except Exception as exc:
                    logger.error(f"Worker error: {exc}")
                    continue
                if results:
                    append_results(results)
                    print(f"✅ Found {len(results)} movies")
                for sub in subdirs:
                    if sub not in visited:
                        queue.append(sub)
    save_state(list(queue), set(visited))
    if stop_flag:
        print("💾 Progress saved. Run again to continue.")
    else:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        print("✅ Crawl completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
