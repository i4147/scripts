import base64
import pathlib
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


def get_base64_uri(url):
    try:
        response = requests.get(url, timeout=10)
        content_type = response.headers.get("Content-Type", "image/png")
        encoded_body = base64.b64encode(response.content).decode("utf-8")
        return f"data:{content_type};base64,{encoded_body}"
    except Exception as e:
        print(f"Could not inline {url}: {e}")
        return url


def save_as_monolith(url, output_file) -> None:
    print(f"Fetching: {url}...")
    response = requests.get(url)
    soup = BeautifulSoup(response.content, "html.parser")
    for img in soup.find_all("img"):
        if img.get("src"):
            img_url = urljoin(url, img["src"])
            img["src"] = get_base64_uri(img_url)
    for link in soup.find_all("link", rel="stylesheet"):
        if link.get("href"):
            css_url = urljoin(url, link["href"])
            try:
                css_content = requests.get(css_url).text
                new_style = soup.new_tag("style")
                new_style.string = css_content
                link.replace_with(new_style)
            except:
                continue
    pathlib.Path(output_file).write_text(soup.prettify(), encoding="utf-8")
    print(f"Saved to {output_file}")
