#!/data/data/com.termux/files/usr/bin/python
from __future__ import annotations
import json
import os
import shutil
import sys
import urllib.request


def get_default_branch(user: str, repo: str, token: str | None) -> str:
    headers = {
        "User-Agent": "zip-downloader",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com/repos/{user}/{repo}", headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    return data["default_branch"]


def download_zip(user: str, repo: str, branch: str, out_path: str, token: str | None) -> None:
    headers = {"User-Agent": "zip-downloader"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://github.com/{user}/{repo}/archive/refs/heads/{branch}.zip"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp, open(out_path, "wb") as f:
        shutil.copyfileobj(resp, f)


def main() -> None:
    slug = sys.argv[1].strip().rstrip("/")
    slug = slug.removesuffix(".git")
    user, repo = slug.split("/")[:2]
    token = os.environ.get("GITHUB_TOKEN")
    branch = get_default_branch(user, repo, token)
    out_path = os.path.abspath(f"{repo}.zip")
    download_zip(user, repo, branch, out_path, token)
    print(out_path)


if __name__ == "__main__":
    main()
