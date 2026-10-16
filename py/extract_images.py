import os
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def extract_and_save_images(url: str, output_dir: str = "downloaded_images") -> int:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        print(f"Fetching content from {url}...")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        img_tags = soup.find_all("img")
        if not img_tags:
            print("No images found on the page.")
            return 0
        print(f"Found {len(img_tags)} images. Starting download...")
        downloaded_count = 0
        for idx, img in enumerate(img_tags, 1):
            try:
                img_url = img.get("src") or img.get("data-src")
                if not img_url:
                    continue
                img_url = urljoin(url, img_url)
                img_response = requests.get(
                    img_url,
                    headers=headers,
                    timeout=10,
                )
                img_response.raise_for_status()
                parsed_url = urlparse(img_url)
                filename = Path(parsed_url.path).name
                if not filename or "." not in filename:
                    filename = f"image_{idx}.jpg"
                filepath = os.path.join(output_dir, filename)
                base, ext = os.path.splitext(filename)
                counter = 1
                while Path(filepath).exists():
                    filepath = os.path.join(
                        output_dir,
                        f"{base}_{counter}{ext}",
                    )
                    counter += 1
                Path(filepath).write_bytes(img_response.content)
                print(f"[{idx}/{len(img_tags)}] Downloaded: {filename}")
                downloaded_count += 1
            except Exception as e:
                print(f"[{idx}/{len(img_tags)}] Error downloading image: {e}")
                continue
        print(f"\nDownload complete! {downloaded_count} images saved to '{output_dir}/' directory.")
        return downloaded_count
    except requests.exceptions.RequestException as e:
        print(f"Error fetching the URL: {e}")
        return 0
    except Exception as e:
        print(f"An error occurred: {e}")
        return 0


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python extract_images.py <URL> [output_directory]")
        print("\nExample:")
        print("  python extract_images.py https://example.com")
        print("  python extract_images.py https://example.com my_images")
        sys.exit(1)
    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "downloaded_images"
    extract_and_save_images(url, output_dir)


if __name__ == "__main__":
    main()
