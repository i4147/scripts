import json
import math
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

PART_SIZE = 10 * 1024 * 1024
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


def head_request(url: str) -> int:
    r = requests.head(url, allow_redirects=True, timeout=10)
    r.raise_for_status()
    if r.headers.get("Accept-Ranges") != "bytes":
        msg = "Server does not support range requests"
        raise RuntimeError(msg)
    return int(r.headers["Content-Length"])


def load_meta(path: str) -> dict:
    if Path(path).exists():
        with Path(path).open(encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_meta(path: str, meta: dict) -> None:
    tmp = path + ".tmp"
    with Path(tmp).open("w", encoding="utf-8") as f:
        json.dump(meta, f)
    Path(tmp).replace(path)


def build_parts(size: int) -> list[tuple[int, int, int]]:
    parts = []
    count = math.ceil(size / PART_SIZE)
    for i in range(count):
        start = i * PART_SIZE
        end = min(start + PART_SIZE - 1, size - 1)
        parts.append((i, start, end))
    return parts


def download_part(
    url: str,
    output: str,
    part_id: int,
    start: int,
    end: int,
    meta: dict,
) -> None:
    part_path = f"{output}.part{part_id}"
    downloaded = meta.get(str(part_id), start)
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
                mode = "ab" if Path(part_path).exists() else "wb"
                with Path(part_path).open(mode) as f:
                    for chunk in r.iter_content(1024 * 64):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        meta[str(part_id)] = downloaded
            return
        except Exception:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_DELAY * (attempt + 1))


def merge_parts(output: str, parts: list[tuple[int, int, int]]) -> None:
    with Path(output).open("wb") as out:
        for part_id, _, _ in parts:
            part_path = f"{output}.part{part_id}"
            with Path(part_path).open("rb") as p:
                while True:
                    buf = p.read(1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)


def cleanup(
    output: str,
    parts: list[tuple[int, int, int]],
    meta_path: str,
) -> None:
    for part_id, _, _ in parts:
        Path(f"{output}.part{part_id}").unlink()
    Path(meta_path).unlink()


def download(url: str, output: str, workers: int) -> None:
    meta_path = output + ".meta.json"
    size = head_request(url)
    parts = build_parts(size)
    meta = load_meta(meta_path)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for part_id, start, end in parts:
                if meta.get(str(part_id), start) > end:
                    continue
                futures.append(
                    pool.submit(
                        download_part,
                        url,
                        output,
                        part_id,
                        start,
                        end,
                        meta,
                    )
                )
            for f in as_completed(futures):
                f.result()
    except GracefulExit:
        save_meta(meta_path, meta)
        print("\nPaused. Resume by re-running.")
        sys.exit(0)
    save_meta(meta_path, meta)
    merge_parts(output, parts)
    cleanup(output, parts, meta_path)
    print("Download completed successfully.")


if __name__ == "__main__":
    if len(sys.argv) < THREE:
        print("Usage: python multipart_downloader.py <url> <output> [workers]")
        sys.exit(1)
    url = sys.argv[1]
    output = sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > THREE else FOUR
    download(url, output, workers)
