from __future__ import annotations

import argparse
import json
import re
import signal
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import Manager, cpu_count
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DEFAULT_URL = "https://sr.moviesho.com/Series/"
STATE_FILE = "crawler_state.json"
TXT_OUTPUT = "movies.txt"
JSON_OUTPUT = "movies.json"
stop_flag = False


def signal_handler(sig, frame) -> None:
    global stop_flag
    print("\n⚠️  Interrupt received! Saving progress...")
    stop_flag = True


signal.signal(signal.SIGINT, signal_handler)


def size_to_mb(size_str: str) -> float | None:
    match = re.search(r"([\d.]+)\s*Mi?B", size_str)
    if match:
        return float(match.group(1))
    return None


def extract_quality(filename: str) -> str | None:
    if "480p" in filename.lower():
        return "480"
    if "720p" in filename.lower():
        return "720"
    return None


def fetch_directory(url) -> str | None:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except Exception:
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


def save_state(queue, visited) -> None:
    state = {"queue": list(queue), "visited": list(visited)}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def load_state():
    if not Path(STATE_FILE).exists():
        return None, None
    with open(STATE_FILE, encoding="utf-8") as f:
        state = json.load(f)
    return set(state["visited"]), state["queue"]


def append_results(results) -> None:
    with open(TXT_OUTPUT, "a", encoding="utf-8") as f:
        f.writelines(r["url"] + "\n" for r in results)
    with open(JSON_OUTPUT, "a", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in results)


def main() -> None:
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
        visited[:] = prev_visited
        queue[:] = prev_queue
    else:
        queue.append(base_url)
    workers = cpu_count()
    print(f"🚀 Using {workers} processes")
    with ProcessPoolExecutor(max_workers=workers) as executor:
        while queue and not stop_flag:
            futures = {}
            for _ in range(min(len(queue), workers)):
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.append(url)
                futures[executor.submit(parse_directory, url, max_size)] = url
            for future in as_completed(futures):
                if stop_flag:
                    break
                results, subdirs = future.result()
                if results:
                    append_results(results)
                    print(f"✅ Found {len(results)} movies")
                for sub in subdirs:
                    if sub not in visited:
                        queue.append(sub)
    save_state(queue, visited)
    if stop_flag:
        print("💾 Progress saved. Run again to continue.")
    else:
        if Path(STATE_FILE).exists():
            Path(STATE_FILE).unlink()
        print("✅ Crawl completed successfully.")


if __name__ == "__main__":
    raise SystemExit(main())
