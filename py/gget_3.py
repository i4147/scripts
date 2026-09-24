import hashlib
import json
import multiprocessing
import signal
import sys
import threading
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote
import requests
from loguru import logger
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

CHUNK_SIZE = 1024 * 1024 * 5
RANGE_CHUNK_SIZE = 32768
MAX_WORKERS = 8
STATE_SUFFIX = ".progress"
HTTP_TIMEOUT = 15
console = Console()


class Downloader:
    def __init__(
        self,
        url,
        output_path=None,
        expected_hash=None,
    ):
        self.url = url
        self.stop_event = threading.Event()
        self.file_size = 0
        self.filename = output_path
        self.expected_hash = expected_hash
        self.state_file = None
        self.progress_data = {"downloaded_chunks": [], "total_chunks": 0}
        self.lock = threading.Lock()

    def _get_info(self):
        resp = requests.head(self.url, allow_redirects=True, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        self.file_size = int(resp.headers.get("content-length", 0))
        if not self.filename:
            cd = resp.headers.get("Content-Disposition")
            if cd and "filename=" in cd:
                self.filename = cd.split("filename=")[1].strip(' "')
            else:
                self.filename = unquote(self.url.split("/")[-1]) or "downloaded_file"
        assert self.filename is not None
        self.state_file = Path(f"{self.filename}{STATE_SUFFIX}")

    def _verify_integrity(self):
        assert self.filename is not None
        sha256_hash = hashlib.sha256()
        print("Verifying file integrity...")
        with Path(self.filename).open("rb") as f:
            for byte_block in iter(lambda: f.read(CHUNK_SIZE), b""):
                sha256_hash.update(byte_block)
        calculated_hash = sha256_hash.hexdigest()
        if self.expected_hash:
            if calculated_hash.lower() == self.expected_hash.lower():
                logger.success("Integrity verified: hashes match!")
            else:
                logger.error("Integrity check failed!")
                logger.error(f"Expected: {self.expected_hash}")
                logger.error(f"Got:      {calculated_hash}")
        else:
            logger.warning(f"SHA-256 checksum: {calculated_hash}")
            print("Provide this hash next time to verify automatically.")

    def _load_state(self):
        if self.state_file is not None and self.state_file.exists():
            try:
                with self.state_file.open(encoding="utf-8") as f:
                    loaded = json.load(f)
                self.progress_data = loaded
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"Could not load state file: {exc}")

    def _save_state(self):
        if self.state_file is None:
            return
        with self.lock, self.state_file.open("w", encoding="utf-8") as f:
            json.dump(self.progress_data, f)

    def _download_chunk(
        self,
        chunk_id,
        start,
        end,
        progress,
        task_id,
    ):
        if self.stop_event.is_set():
            return
        headers = {"Range": f"bytes={start}-{end}"}
        try:
            with requests.get(self.url, headers=headers, stream=True, timeout=HTTP_TIMEOUT) as r:
                r.raise_for_status()
                assert self.filename is not None
                with Path(self.filename).open("r+b") as f:
                    f.seek(start)
                    for data in r.iter_content(chunk_size=1024 * 64):
                        if self.stop_event.is_set():
                            return
                        f.write(data)
                        try:
                            progress.update(task_id, advance=len(data))
                        except Exception:
                            pass
            with self.lock:
                self.progress_data["downloaded_chunks"].append(chunk_id)
            self._save_state()
        except Exception as exc:
            logger.debug(f"Chunk {chunk_id} failed: {exc}")

    def start(self):
        self._get_info()
        self._load_state()
        assert self.filename is not None
        if not Path(self.filename).exists():
            with Path(self.filename).open("wb") as f:
                f.truncate(self.file_size)
        chunks = [
            (i, min(i + RANGE_CHUNK_SIZE - 1, self.file_size - 1)) for i in range(0, self.file_size, RANGE_CHUNK_SIZE)
        ]
        self.progress_data["total_chunks"] = len(chunks)
        downloaded = list(self.progress_data.get("downloaded_chunks", []))
        pending_chunks = [(idx, s, e) for idx, (s, e) in enumerate(chunks) if idx not in downloaded]
        if not pending_chunks:
            logger.success(f"{self.filename} is already finished!")
            self._verify_integrity()
            return

        def _sigint_handler(signum, frame):
            self.stop_event.set()

        signal.signal(signal.SIGINT, _sigint_handler)
        with Progress(
            TextColumn("[bold blue]{task.fields[filename]}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            main_task = progress.add_task(
                "download",
                filename=self.filename,
                total=self.file_size,
                completed=len(downloaded) * RANGE_CHUNK_SIZE,
            )
            pool = multiprocessing.Pool(processes=MAX_WORKERS)
            async_results = []
            try:
                for cid, s, e in pending_chunks:
                    ar = pool.apply_async(
                        self._download_chunk,
                        args=(cid, s, e, progress, main_task),
                    )
                    async_results.append(ar)
                for ar in async_results:
                    if self.stop_event.is_set():
                        break
                    try:
                        ar.get()
                    except Exception as exc:
                        logger.debug(f"Worker raised: {exc}")
            finally:
                pool.close()
                pool.join()
        if not self.stop_event.is_set():
            if self.state_file is not None:
                self.state_file.unlink(missing_ok=True)
            logger.success(f"Download complete: {self.filename}")
            self._verify_integrity()
        else:
            logger.warning("Download paused. Run again to resume.")
            sys.exit(0)


def main():
    if len(sys.argv) < 2:
        logger.error("Usage: python downloader.py <URL> [output_name] [expected_sha256]")
        sys.exit(1)
    url_arg = sys.argv[1]
    out_arg = sys.argv[2] if len(sys.argv) > 2 else None
    hash_arg = sys.argv[3] if len(sys.argv) > 3 else None
    dl = Downloader(url_arg, out_arg, hash_arg)
    dl.start()


if __name__ == "__main__":
    main()
