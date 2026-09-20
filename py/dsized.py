import argparse
import urllib.error
import urllib.request
from pathlib import Path

MAX_DOWNLOAD_SIZE = 1 * 1024 * 1024


def fetch_content_length(url: str) -> int | None:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            length = response.headers.get("Content-Length")
            if length:
                return int(length)
    except urllib.error.HTTPError as e:
        if e.code not in {405, 403}:
            raise
    request = urllib.request.Request(url, method="GET")
    request.add_header("Range", "bytes=0-0")
    with urllib.request.urlopen(request, timeout=10) as response:
        length = response.headers.get("Content-Length")
        return int(length) if length else None


def format_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"


def download_file(url: str, dest_dir: Path) -> None:
    filename = Path(urllib.request.urlparse(url).path).name or "downloaded_file"
    dest_file = dest_dir / filename
    try:
        urllib.request.urlretrieve(url, dest_file)
        print(f"Downloaded: {dest_file}")
    except Exception as e:
        print(f"Failed to download {url}: {e}")


def process_url(url: str, download_dir: Path | None = None) -> str:
    try:
        size = fetch_content_length(url)
        if size is None:
            return f"{url}\tUnknown"
        size_str = format_size(size)
        if download_dir and size <= MAX_DOWNLOAD_SIZE:
            download_file(url, download_dir)
        return f"{url}\t{size_str}"
    except Exception as exc:
        return f"{url}\tError: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Show download size of a URL or URLs from a file")
    parser.add_argument(
        "input",
        help="Download URL or file containing URLs",
    )
    parser.add_argument(
        "-d",
        "--download",
        help="Directory to download files smaller than 5MB",
    )
    args = parser.parse_args()
    download_dir = Path(args.download) if args.download else None
    if download_dir:
        download_dir.mkdir(parents=True, exist_ok=True)
    input_path = Path(args.input)
    if input_path.is_file():
        lines = input_path.read_text(encoding="utf-8").splitlines()
        updated_lines = [process_url(line.strip(), download_dir) for line in lines if line.strip()]
        input_path.write_text(
            "\n".join(updated_lines),
            encoding="utf-8",
        )
        print(f"Updated file: {input_path} ({len(updated_lines)} URLs processed)")
    else:
        print(process_url(args.input, download_dir))


if __name__ == "__main__":
    main()
