from __future__ import annotations

import hashlib
import json
import signal
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote

import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console = Console()
CHUNK_SIZE = 1024 * 1024 * 5
MAX_WORKERS = 4
STATE_SUFFIX = ".progress"


class Downloader:
    def __init__(self, url, output_path=None, expected_hash=None) -> None:
        self.url = url
        self.stop_event = threading.Event()
        self.file_size = 0
        self.filename = output_path
        self.expected_hash = expected_hash
        self.state_file = None
        self.progress_data = {"downloaded_chunks": [], "total_chunks": 0}
        self.lock = threading.Lock()

    def _get_info(self) -> None:
        resp = requests.head(self.url, allow_redirects=True, timeout=10)
        resp.raise_for_status()
        self.file_size = int(resp.headers.get("content-length", 0))
        if not self.filename:
            cd = resp.headers.get("Content-Disposition")
            if cd and "filename=" in cd:
                self.filename = cd.split("filename=")[1].strip(' "')
            else:
                self.filename = unquote(self.url.split("/")[-1]) or "downloaded_file"
        self.state_file = Path(f"{self.filename}{STATE_SUFFIX}")

    def _verify_integrity(self) -> None:
        sha256_hash = hashlib.sha256()
        console.print("\n[bold cyan]Verifying file integrity...[/]")
        with Path(self.filename).open("rb") as f:
            for byte_block in iter(lambda: f.read(1024 * 1024), b""):
                sha256_hash.update(byte_block)
        calculated_hash = sha256_hash.hexdigest()
        if self.expected_hash:
            if calculated_hash.lower() == self.expected_hash.lower():
                console.print("[bold green]✅ Integrity Verified: Hashes match![/]")
            else:
                console.print("[bold red]❌ Integrity Check Failed![/]")
                console.print(f"Expected: {self.expected_hash}")
                console.print(f"Got:      {calculated_hash}")
        else:
            console.print(f"[bold yellow]SHA-256 Checksum:[/] {calculated_hash}")
            console.print("[italic]Provide this hash next time to verify automatically.[/]")

    def _load_state(self) -> None:
        if self.state_file.exists():
            try:
                with Path(self.state_file).open(encoding="utf-8") as f:
                    self.progress_data = json.load(f)
            except Exception:
                pass

    def _save_state(self) -> None:
        with self.lock, Path(self.state_file).open("w", encoding="utf-8") as f:
            json.dump(self.progress_data, f)

    def _download_chunk(self, chunk_id, start, end, progress, task_id) -> None:
        if self.stop_event.is_set():
            return
        headers = {"Range": f"bytes={start}-{end}"}
        try:
            with requests.get(self.url, headers=headers, stream=True, timeout=15) as r:
                r.raise_for_status()
                with Path(self.filename).open("r+b") as f:
                    f.seek(start)
                    for data in r.iter_content(chunk_size=1024 * 64):
                        if self.stop_event.is_set():
                            return
                        f.write(data)
                        progress.update(task_id, advance=len(data))
            with self.lock:
                self.progress_data["downloaded_chunks"].append(chunk_id)
            self._save_state()
        except Exception:
            pass

    def start(self) -> None:
        self._get_info()
        self._load_state()
        if not Path(self.filename).exists():
            with Path(self.filename).open("wb") as f:
                f.truncate(self.file_size)
        chunks = [(i, min(i + 32768 - 1, self.file_size - 1)) for i in range(0, self.file_size, 32768)]
        self.progress_data["total_chunks"] = len(chunks)
        pending_chunks = [
            (idx, s, e) for idx, (s, e) in enumerate(chunks) if idx not in self.progress_data["downloaded_chunks"]
        ]
        if not pending_chunks:
            console.print(f"[bold green]✔ {self.filename} is already finished![/]")
            self._verify_integrity()
            return
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
                completed=len(self.progress_data["downloaded_chunks"]) * 32768,
            )
            signal.signal(signal.SIGINT, lambda s, f: self.stop_event.set())
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = [
                    executor.submit(self._download_chunk, cid, s, e, progress, main_task)
                    for cid, s, e in pending_chunks
                ]
                for f in futures:
                    if self.stop_event.is_set():
                        break
                    f.result()
        if not self.stop_event.is_set():
            self.state_file.unlink(missing_ok=True)
            console.print(f"\n[bold green]Download Complete: {self.filename}[/]")
            self._verify_integrity()
        else:
            console.print("\n[bold yellow]Download Paused. Run again to resume.[/]")
            sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print("[bold red]Usage:[/] python downloader.py <URL> [output_name] [expected_sha256]")
        sys.exit(1)
    url_arg = sys.argv[1]
    out_arg = sys.argv[2] if len(sys.argv) > 2 else None
    hash_arg = sys.argv[3] if len(sys.argv) > 3 else None
    dl = Downloader(url_arg, out_arg, hash_arg)
    dl.start()
