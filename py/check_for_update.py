import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


def get_latest_version_info(pkg_name: str, mirror_url: str) -> dict:
    package_url = f"{mirror_url}/{pkg_name}"
    output_data = {
        "pkg_name": pkg_name,
        "latest_version": None,
        "url_of_latest_version": None,
        "html_content": None,
        "error": None,
    }
    try:
        response = requests.get(package_url)
        response.raise_for_status()
        output_data["html_content"] = response.text
        output_dir = "output"
        if not Path(output_dir).exists():
            Path(output_dir).mkdir(parents=True)
        Path(os.path.join(output_dir, f"{pkg_name}_debug.html")).write_text(response.text, encoding="utf-8")
        soup = BeautifulSoup(response.text, "html.parser")
        links = soup.find_all("a")
        if not links:
            output_data["error"] = "No links found for the package."
            return output_data
        latest_link_tag = links[-1]
        latest_url = latest_link_tag.get("href")
        if not latest_url:
            output_data["error"] = "Could not extract URL from the last link tag."
            return output_data
        full_latest_url = urljoin(mirror_url, latest_url)
        preferred_url = None
        sorted_links = sorted(
            links,
            key=lambda x: (
                ".tar.gz" not in x.get("href", ""),
                ".zip" not in x.get("href", ""),
                ".whl" not in x.get("href", ""),
            ),
        )
        for link_tag in sorted_links:
            href = link_tag.get("href")
            if href:
                if href.endswith(".tar.gz"):
                    preferred_url = urljoin(mirror_url, href)
                    break
                if href.endswith(".zip") or (href.endswith(".whl") and (not preferred_url)):
                    preferred_url = urljoin(mirror_url, href)
        if not preferred_url:
            output_data["error"] = "Could not find a preferred file type (.tar.gz, .zip, or .whl)."
            return output_data
        version_match = re.search("([\\w.-]+?)-(\\d+\\.\\d+(\\.\\d+)?(-\\w+)?).*\\.(tar\\.gz|zip|whl)", preferred_url)
        if version_match:
            output_data["latest_version"] = version_match.group(2)
        else:
            version_match_fallback = re.search("-(\\d+\\.\\d+(\\.\\d+)?(-\\w+)?)\\.", latest_url)
            if version_match_fallback:
                output_data["latest_version"] = version_match_fallback.group(1)
            else:
                output_data["error"] = "Could not extract version number from URL."
                return output_data
        output_data["url_of_latest_version"] = preferred_url
    except requests.exceptions.RequestException as e:
        output_data["error"] = f"Request error: {e}"
    except Exception as e:
        output_data["error"] = f"An unexpected error occurred: {e}"
    return output_data


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python script_name.py <path_to_package_list_file>")
        sys.exit(1)
    package_list_file = sys.argv[1]
    mirror_url = "https://mirror-pypi.runflare.com"
    output_json_file = "package_versions.json"
    all_results = []
    try:
        with Path(package_list_file).open("r", encoding="utf-8") as f:
            package_names = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"Error: File not found at {package_list_file}")
        sys.exit(1)
    for pkg_name in package_names:
        print(f"Processing: {pkg_name}...")
        result = get_latest_version_info(pkg_name, mirror_url)
        all_results.append(result)
        try:
            with Path(output_json_file).open("w", encoding="utf-8") as f:
                json.dump(all_results, f, indent=4, ensure_ascii=False)
        except OSError as e:
            print(f"Error writing to JSON file {output_json_file}: {e}")
    print(f"\nProcessing complete. Results saved to {output_json_file}")


if __name__ == "__main__":
    main()
