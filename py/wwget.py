import json
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

CHUNK_SIZE = 5 * 1024 * 1024
MAX_RETRIES = 5
RETRY_DELAY = 2
THREE = 3
FOUR = 4


class GracefulExit(Exception):
    pass


def _signal_handler(signum, frame):
    raise GracefulExit


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def head_request(url: str) -> tuple[int, bool]:
    r = requests.head(url, allow_redirects=True, timeout=10)
    r.raise_for_status()
    size = int(r.headers.get("Content-Length", 0))
    ranges = r.headers.get("Accept-Ranges", "") == "bytes"
    if not ranges:
        msg = "Server does not support byte-range requests."
        raise RuntimeError(msg)
    return size, ranges


def init_files(path: str, size: int) -> None:
    if not Path(path).exists():
        with Path(path).open("wb") as f:
            f.truncate(size)


def load_meta(meta_path: str) -> dict:
    if Path(meta_path).exists():
        with Path(meta_path).open(encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_meta(meta_path: str, meta: dict) -> None:
    tmp = meta_path + ".tmp"
    with Path(tmp).open("w", encoding="utf-8") as f:
        json.dump(meta, f)
    Path(tmp).replace(meta_path)


def build_chunks(size: int) -> list[tuple[int, int]]:
    chunks = []
    for i in range(0, size, CHUNK_SIZE):
        end = min(i + CHUNK_SIZE - 1, size - 1)
        chunks.append((i, end))
    return chunks


def download_chunk(
    url: str,
    path: str,
    start: int,
    end: int,
    meta: dict,
    meta_lock: threading.Lock,
) -> None:
    downloaded = meta.get(str(start), start)
    if downloaded > end:
        return
    headers = {"Range": f"bytes={downloaded}-{end}"}
    for attempt in range(MAX_RETRIES):
        try:
            with requests.get(
                url,
                headers=headers,
                stream=True,
                timeout=15,
            ) as r:
                r.raise_for_status()
                with Path(path).open("r+b") as f:
                    f.seek(downloaded)
                    for chunk in r.iter_content(1024 * 64):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        with meta_lock:
                            meta[str(start)] = downloaded
            return
        except Exception:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_DELAY * (attempt + 1))


def download(url: str, output: str, workers: int = 4) -> None:
    meta_path = output + ".meta"
    size, _ = head_request(url)
    init_files(output, size)
    meta = load_meta(meta_path)
    meta_lock = threading.Lock()
    chunks = build_chunks(size)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for start, end in chunks:
                futures.append(
                    pool.submit(
                        download_chunk,
                        url,
                        output,
                        start,
                        end,
                        meta,
                        meta_lock,
                    )
                )
            for f in as_completed(futures):
                f.result()
    except GracefulExit:
        save_meta(meta_path, meta)
        print("\nPaused. Resume by re-running the script.")
        sys.exit(0)
    save_meta(meta_path, meta)
    if Path(output).stat().st_size == size:
        Path(meta_path).unlink()
        print("Download completed successfully.")


if __name__ == "__main__":
    if len(sys.argv) < THREE:
        print("Usage: python downloader.py <url> <output_file> [workers]")
        sys.exit(1)
    url = sys.argv[1]
    output = sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > THREE else FOUR
    download(url, output, workers)
