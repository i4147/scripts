import json
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, unquote
from typing import Optional, List, Dict
import requests

from .constants import PYPI_INDEX, PYPI_SIMPLE, DEFAULT_TIMEOUT, MAX_WORKERS


class PackageNotFound(Exception):
    pass


class Downloader:
    def __init__(self, output_dir: str = ".", timeout: int = DEFAULT_TIMEOUT, max_workers: int = MAX_WORKERS):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_workers = max_workers
        self.session = requests.Session()

    def get_package_info(self, package: str, version: Optional[str] = None) -> dict:
        url = f"{PYPI_INDEX}/{package}/json"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise PackageNotFound(f"Package '{package}' not found: {e}")

        data = resp.json()
        if version and version not in data["releases"]:
            raise PackageNotFound(f"Version {version} not found for {package}")

        return data

    def get_releases(self, package: str, version: Optional[str] = None) -> list[dict]:
        info = self.get_package_info(package, version)

        if version:
            releases = info["releases"].get(version, [])
        else:
            latest = info["info"]["version"]
            releases = info["releases"].get(latest, [])

        return releases

    def _download_file(self, url: str, filename: str) -> tuple[str, bool]:
        filepath = self.output_dir / filename
        try:
            resp = self.session.get(url, timeout=self.timeout, stream=True)
            resp.raise_for_status()
            filepath.write_bytes(resp.content)
            return str(filepath), True
        except Exception as e:
            return str(filepath), False

    def download(
        self, package: str, version: Optional[str] = None, prefer_wheels: bool = True, parallel: bool = True
    ) -> list[str]:
        releases = self.get_releases(package, version)

        if not releases:
            raise PackageNotFound(f"No distributions found for {package}")

        filtered = self._filter_releases(releases, prefer_wheels)

        if not filtered:
            filtered = releases

        if parallel and len(filtered) > 1:
            return self._parallel_download(filtered)

        return self._serial_download(filtered)

    def _filter_releases(self, releases: list[dict], prefer_wheels: bool) -> list[dict]:
        if not prefer_wheels:
            return releases

        wheels = [r for r in releases if r["filename"].endswith(".whl")]
        return wheels if wheels else []

    def _serial_download(self, releases: list[dict]) -> list[str]:
        results = []
        for release in releases:
            path, success = self._download_file(release["url"], release["filename"])
            if success:
                results.append(path)
        return results

    def _parallel_download(self, releases: list[dict]) -> list[str]:
        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._download_file, r["url"], r["filename"]): r for r in releases}
            for future in as_completed(futures):
                path, success = future.result()
                if success:
                    results.append(path)
        return results
