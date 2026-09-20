import os
import pathlib
import sys

import requests
from bs4 import BeautifulSoup


def extract_images(url: str) -> None:
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        img_tags = soup.find_all("img")
        if not pathlib.Path("extracted_images").exists():
            pathlib.Path("extracted_images").mkdir(parents=True)
        for img in img_tags:
            img_url = img.get("src")
            if img_url:
                if not img_url.startswith("http"):
                    img_url = requests.compat.urljoin(url, img_url)
                img_name = os.path.join(
                    "extracted_images",
                    pathlib.Path(img_url).name,
                )
                with pathlib.Path(img_name).open("wb") as f:
                    img_data = requests.get(img_url).content
                    f.write(img_data)
        print("Images extracted and saved to extracted_images folder.")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python extract_images.py <url>")
        sys.exit(1)
    url = sys.argv[1]
    extract_images(url)
