from __future__ import annotations

import hashlib
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pycurl


RETRIES = 3
TIMEOUT = 30
CHUNK_SIZE = 1024 * 1024
CHUNK_THRESHOLD = 5 * 1024 * 1024

MIRRORS = [
    "https://pypi.org",
    "https://pypi.tuna.tsinghua.edu.cn",
    "https://mirror-pypi.runflare.com",
]

CURRENT_DIR = Path.cwd()


def parse_requirement(value: str) -> tuple[str, str | None]:
    match = re.match(r"^([A-Za-z0-9_.-]+)(?:==([A-Za-z0-9_.!+-]+))?$", value)

    if match:
        return match.group(1), match.group(2)

    package_name = re.split(r"[<>=!~\[]", value, maxsplit=1)[0].strip()
    if not package_name:
        raise ValueError(f"Invalid package specification: {value!r}")

    print(f"Warning: {value!r} is not an exact version specification; downloading the latest release.")
    return package_name, None


def normalized_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def curl_get_bytes(url: str, byte_range: str | None = None) -> bytes:
    response = bytearray()

    curl = pycurl.Curl()
    try:
        curl.setopt(pycurl.URL, url)
        curl.setopt(pycurl.FOLLOWLOCATION, True)
        curl.setopt(pycurl.MAXREDIRS, 5)
        curl.setopt(pycurl.CONNECTTIMEOUT, TIMEOUT)
        curl.setopt(pycurl.TIMEOUT, TIMEOUT)
        curl.setopt(pycurl.USERAGENT, "pypi-package-downloader/1.0")
        curl.setopt(pycurl.WRITEFUNCTION, response.extend)

        if byte_range is not None:
            curl.setopt(pycurl.RANGE, byte_range)

        curl.perform()

        status = curl.getinfo(pycurl.RESPONSE_CODE)
        if status not in (200, 206):
            raise RuntimeError(f"HTTP {status}")

        return bytes(response)
    finally:
        curl.close()


def fetch_json(url: str) -> dict[str, Any]:
    import json

    return json.loads(curl_get_bytes(url).decode("utf-8"))


def get_package_metadata(package: str, mirror: str) -> dict[str, Any]:
    package_url = quote(normalized_package_name(package), safe="")
    return fetch_json(f"{mirror}/pypi/{package_url}/json")


def is_compatible_file(file_info: dict[str, Any]) -> bool:
    filename = file_info.get("filename", "").lower()
    package_type = file_info.get("packagetype", "")

    if "darwin" in filename or "macosx" in filename or "win32" in filename:
        return False

    if package_type == "sdist":
        return filename.endswith(".tar.gz")

    if package_type == "bdist_wheel":
        return (
            filename.endswith(".whl")
            and re.search(
                r"-(py\d|py2\.py3)-none-any\.whl$",
                filename,
            )
            is not None
        )

    return False


def choose_distribution(
    metadata: dict[str, Any],
    requested_version: str | None,
) -> dict[str, Any]:
    version = requested_version or metadata["info"]["version"]
    releases = metadata.get("releases", {})

    files = releases.get(version, [])
    if not files:
        raise RuntimeError(f"No files found for version {version}")

    valid_files = [
        file_info for file_info in files if not file_info.get("yanked", False) and is_compatible_file(file_info)
    ]

    tarballs = [
        file_info
        for file_info in valid_files
        if file_info.get("packagetype") == "sdist" and file_info.get("filename", "").endswith(".tar.gz")
    ]
    if tarballs:
        return tarballs[0]

    wheels = [file_info for file_info in valid_files if file_info.get("packagetype") == "bdist_wheel"]
    if wheels:
        return wheels[0]

    raise RuntimeError(f"No suitable .tar.gz source package or universal Python wheel was found for version {version}")


def get_content_length(url: str) -> int | None:
    curl = pycurl.Curl()
    try:
        curl.setopt(pycurl.URL, url)
        curl.setopt(pycurl.NOBODY, True)
        curl.setopt(pycurl.FOLLOWLOCATION, True)
        curl.setopt(pycurl.MAXREDIRS, 5)
        curl.setopt(pycurl.CONNECTTIMEOUT, TIMEOUT)
        curl.setopt(pycurl.TIMEOUT, TIMEOUT)
        curl.setopt(pycurl.USERAGENT, "pypi-package-downloader/1.0")
        curl.perform()

        size = curl.getinfo(pycurl.CONTENT_LENGTH_DOWNLOAD_T)
        return size if size >= 0 else None
    finally:
        curl.close()


def format_size(size: int | None) -> str:
    if size is None:
        return "unknown size"

    units = ("B", "KiB", "MiB", "GiB")
    value = float(size)

    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024

    return f"{size} B"


def download_regular(url: str, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")

    with temporary.open("wb") as file_handle:
        curl = pycurl.Curl()
        try:
            curl.setopt(pycurl.URL, url)
            curl.setopt(pycurl.FOLLOWLOCATION, True)
            curl.setopt(pycurl.MAXREDIRS, 5)
            curl.setopt(pycurl.CONNECTTIMEOUT, TIMEOUT)
            curl.setopt(pycurl.TIMEOUT, TIMEOUT)
            curl.setopt(pycurl.USERAGENT, "pypi-package-downloader/1.0")
            curl.setopt(pycurl.WRITEFUNCTION, file_handle.write)
            curl.perform()

            status = curl.getinfo(pycurl.RESPONSE_CODE)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
        finally:
            curl.close()

    temporary.replace(destination)


def download_chunked(url: str, destination: Path, total_size: int) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")

    with temporary.open("wb") as file_handle:
        downloaded = 0

        while downloaded < total_size:
            end = min(downloaded + CHUNK_SIZE - 1, total_size - 1)
            print(
                f"\rDownloading chunk {downloaded // CHUNK_SIZE + 1} "
                f"({format_size(downloaded)} / {format_size(total_size)})",
                end="",
                flush=True,
            )

            chunk = curl_get_bytes(url, f"{downloaded}-{end}")
            expected_size = end - downloaded + 1

            if len(chunk) != expected_size:
                raise RuntimeError(f"Invalid chunk size: expected {expected_size}, got {len(chunk)}")

            file_handle.write(chunk)
            downloaded += len(chunk)

    print()
    temporary.replace(destination)


def verify_hash(path: Path, hashes: dict[str, str]) -> None:
    expected_sha256 = hashes.get("sha256")
    if not expected_sha256:
        return

    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        while data := file_handle.read(1024 * 1024):
            digest.update(data)

    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"SHA256 mismatch for {path.name}: expected {expected_sha256}, got {actual_sha256}")


def download_from_mirror(
    package: str,
    requested_version: str | None,
    mirror: str,
) -> Path:
    metadata = get_package_metadata(package, mirror)
    selected = choose_distribution(metadata, requested_version)

    filename = selected["filename"]
    package_url = quote(normalized_package_name(package), safe="")
    file_url = f"{mirror}/packages/{selected['url'].split('/packages/', 1)[-1]}"

    original_url = selected["url"]
    if "/packages/" in original_url:
        file_url = mirror.rstrip("/") + "/packages/" + original_url.split("/packages/", 1)[1]
    else:
        file_url = original_url

    destination = CURRENT_DIR / filename
    expected_size = selected.get("size") or get_content_length(file_url)

    print(f"Package:  {package}")
    print(f"Mirror:   {mirror}")
    print(f"File:     {filename}")
    print(f"Size:     {format_size(expected_size)}")

    if destination.exists():
        print(f"Already exists: {destination}")
        return destination

    if expected_size is not None and expected_size > CHUNK_THRESHOLD:
        print("Method:   chunked download")
        download_chunked(file_url, destination, expected_size)
    else:
        print("Method:   regular download")
        download_regular(file_url, destination)

    verify_hash(destination, selected.get("digests", {}))
    print(f"Saved:    {destination}")
    return destination


def download_package(specification: str) -> None:
    package, version = parse_requirement(specification)
    errors: list[str] = []

    for mirror in MIRRORS:
        for attempt in range(1, RETRIES + 1):
            try:
                download_from_mirror(package, version, mirror)
                return
            except Exception as error:
                message = f"{mirror} attempt {attempt}/{RETRIES} failed: {error}"
                print(message, file=sys.stderr)
                errors.append(message)

                if attempt < RETRIES:
                    time.sleep(1)

        print(f"Trying next mirror for {package}...", file=sys.stderr)

    raise RuntimeError(f"Failed to download {specification} from all mirrors:\n" + "\n".join(errors))


def main() -> int:
    if len(sys.argv) < 2:
        print(
            f"Usage: {Path(sys.argv[0]).name} PACKAGE [PACKAGE ...]\n"
            "Examples:\n"
            f"  {Path(sys.argv[0]).name} requests\n"
            f"  {Path(sys.argv[0]).name} requests==2.32.3 flask"
        )
        return 2

    failed = False

    for specification in sys.argv[1:]:
        try:
            download_package(specification)
        except Exception as error:
            failed = True
            print(f"ERROR: {specification}: {error}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
