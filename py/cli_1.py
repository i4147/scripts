import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import os
import sys
import time


def main():
    if len(sys.argv) < 2:
        print("Usage: wget2 <URL> [connections]")
        sys.exit(1)
    url = sys.argv[1]
    num_connections = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    filename = os.path.basename(urlparse(url).path) or "downloaded_file"
    resp = requests.head(url, allow_redirects=True)
    if "content-length" not in resp.headers:
        raise Exception("Server does not provide content-length.")
    file_size = int(resp.headers["content-length"])
    print(f"File: {filename} | Size: {file_size / 1024 / 1024:.2f} MB | Connections: {num_connections}")
    chunk_size = file_size // num_connections
    ranges = [(i * chunk_size, (i + 1) * chunk_size - 1) for i in range(num_connections)]
    ranges[-1] = (ranges[-1][0], file_size - 1)

    def download_range(r):
        start, end = r
        headers = {"Range": f"bytes={start}-{end}"}
        r = requests.get(url, headers=headers, stream=True)
        return start, r.content

    start_time = time.time()
    downloaded = 0
    results = []
    with ThreadPoolExecutor(max_workers=num_connections) as executor:
        futures = {executor.submit(download_range, r): r for r in ranges}
        for future in as_completed(futures):
            part_start, data = future.result()
            results.append((part_start, data))
            downloaded += len(data)
            elapsed = time.time() - start_time
            speed = downloaded / elapsed if elapsed > 0 else 0
            remaining = (file_size - downloaded) / speed if speed > 0 else 0
            percent = (downloaded / file_size) * 100
            sys.stdout.write(
                f"\rProgress: {percent:.2f}% | Speed: {speed / 1024 / 1024:.2f} MB/s | ETA: {remaining:.1f} sec"
            )
            sys.stdout.flush()
    results.sort(key=lambda x: x[0])
    with open(filename, "wb") as f:
        for _, data in results:
            f.write(data)
    print(f"\n✅ Download complete: {filename}")


if __name__ == "__main__":
    main()
