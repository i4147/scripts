import os
import pathlib
import sys

import requests
from bs4 import BeautifulSoup


def download_image(url, folder: str) -> None:
    try:
        response = requests.get(url)
        if response.status_code == 200:
            image_name = os.path.join(folder, url.split("/")[-1])
            pathlib.Path(image_name).write_bytes(response.content)
            print(f"Downloaded: {image_name}")
        else:
            print(f"Failed to retrieve image from {url}")
    except Exception as e:
        print(f"An error occurred: {e}")


def extract_images(page_url: str):
    try:
        response = requests.get(page_url)
        soup = BeautifulSoup(response.text, "html.parser")
        images = soup.find_all("img")
        return [img["src"] for img in images if "src" in img.attrs]
    except Exception as e:
        print(f"An error occurred while fetching the page: {e}")
        return []


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python script.py <URL>")
        sys.exit(1)
    url = sys.argv[1]
    folder = "images"
    if not pathlib.Path(folder).exists():
        pathlib.Path(folder).mkdir(parents=True)
    image_urls = extract_images(url)
    for img_url in image_urls:
        if not img_url.startswith("http"):
            img_url = requests.compat.urljoin(url, img_url)
        download_image(img_url, folder)


if __name__ == "__main__":
    main()
