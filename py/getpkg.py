import sys
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse


MIRRORS = [
    "https://pypi.org/pypi",
    "https://pypi.tuna.tsinghua.edu.cn/pypi",
    "https://mirror-pypi.runflare.com/pypi",
]


RETRY_COUNT = 3
TIMEOUT = 30
CHUNK_THRESHOLD = 5 * 1024 * 1024  


def fetch_pypi_metadata(pkg_name: str) -> dict:
    import urllib.request
    import urllib.error

    
    clean_name = pkg_name.split("==")[0].split(">=")[0].split("<=")[0].strip()

    for mirror in MIRRORS:
        url = f"{mirror}/{clean_name}/json"
        for attempt in range(RETRY_COUNT):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "PyPIDownloader/1.0"})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                    if response.status == 200:
                        return json.loads(response.read().decode("utf-8"))
            except urllib.error.URLError:
                continue
            except Exception:
                continue

    raise RuntimeError(f"Failed to fetch metadata for '{pkg_name}' from all mirrors.")


def select_best_release_file(metadata: dict, target_version: str = None) -> dict:
    releases = metadata.get("releases", {})

    
    version = target_version or metadata.get("info", {}).get("version")
    if not version or version not in releases:
        raise ValueError(f"Version '{version}' not found in package metadata.")

    files = releases[version]
    valid_files = []

    for file_info in files:
        filename = file_info["filename"].lower()

        
        if "darwin" in filename or "win32" in filename or "win_amd64" in filename or "win_" in filename:
            continue

        
        
        if filename.endswith(".whl"):
            
            if "none-any" not in filename:
                continue

        valid_files.append(file_info)

    if not valid_files:
        raise RuntimeError(f"No suitable source or neutral wheel release files found for version {version}.")

    
    sdist_files = [f for f in valid_files if f["filename"].endswith(".tar.gz")]
    if sdist_files:
        return sdist_files[0]

    whl_files = [f for f in valid_files if f["filename"].endswith(".whl")]
    if whl_files:
        return whl_files[0]

    return valid_files[0]


def download_with_pycurl(url: str, dest_path: Path):
    import pycurl

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            with open(dest_path, "wb") as f:
                c = pycurl.Curl()
                c.setopt(c.URL, url)
                c.setopt(c.WRITEDATA, f)
                c.setopt(c.TIMEOUT, TIMEOUT)
                c.setopt(c.CONNECTTIMEOUT, TIMEOUT)
                c.setopt(c.FOLLOWLOCATION, True)
                c.perform()
                c.close()
            return
        except pycurl.Error as e:
            if attempt == RETRY_COUNT:
                raise e


def download_with_requests(url: str, dest_path: Path, use_chunks: bool):
    import requests

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            response = requests.get(url, stream=use_chunks, timeout=TIMEOUT)
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                if use_chunks:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                else:
                    f.write(response.content)
            return
        except requests.RequestException as e:
            if attempt == RETRY_COUNT:
                raise e


def download_with_aria2c(url: str, dest_path: Path):
    cmd = [
        "aria2c",
        "--max-tries=" + str(RETRY_COUNT),
        "--timeout=" + str(TIMEOUT),
        "--dir=" + str(dest_path.parent.resolve()),
        "--out=" + dest_path.name,
        "--allow-overwrite=true",
        url,
    ]
    subprocess.run(cmd, check=True)


def download_file(url: str, dest_path: Path, file_size: int, backend: str):
    is_chunked = file_size > CHUNK_THRESHOLD
    print(f"File size: {file_size / (1024 * 1024):.2f} MB | Chunked download: {is_chunked}")

    if backend == "pycurl":
        download_with_pycurl(url, dest_path)
    elif backend == "requests":
        download_with_requests(url, dest_path, is_chunked)
    elif backend == "aria2c":
        download_with_aria2c(url, dest_path)
    else:
        raise ValueError(f"Unsupported backend engine: {backend}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <pkg1> [pkg2==1.0.0 ...] [--backend=pycurl|requests|aria2c]")
        sys.exit(1)

    
    args = sys.argv[1:]
    backend = "pycurl"

    packages = []
    for arg in args:
        if arg.startswith("--backend="):
            backend = arg.split("=")[1].strip()
        else:
            packages.append(arg)

    if not packages:
        print("Error: No package name specified.")
        sys.exit(1)

    output_dir = Path.cwd()

    for pkg_spec in packages:
        print(f"\n---> Processing package specifier: {pkg_spec}")

        
        if "==" in pkg_spec:
            pkg_name, target_ver = pkg_spec.split("==", 1)
        else:
            pkg_name, target_ver = pkg_spec, None

        try:
            metadata = fetch_pypi_metadata(pkg_name)
            file_meta = select_best_release_file(metadata, target_ver)

            download_url = file_meta["url"]
            filename = file_meta["filename"]
            file_size = file_meta.get("size", 0)
            target_file_path = output_dir / filename

            print(f"Selected file : {filename}")
            print(f"Target URL    : {download_url}")

            download_file(download_url, target_file_path, file_size, backend)
            print(f"Successfully downloaded: {target_file_path.name}")

        except Exception as err:
            print(f"Failed to process '{pkg_spec}': {err}")


if __name__ == "__main__":
    main()
