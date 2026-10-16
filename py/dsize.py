import argparse
import sys
import urllib.error
import urllib.request


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Show download size of a URL")
    parser.add_argument("url", help="Download URL")
    args = parser.parse_args()
    try:
        size = fetch_content_length(args.url)
        if size is None:
            print("Unable to determine download size")
            sys.exit(1)
        print(f"Download size: {format_size(size)} ({size} bytes)")
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
