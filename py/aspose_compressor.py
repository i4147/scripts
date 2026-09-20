import requests


class DownloadedFile:
    def __init__(self, link: str) -> None:
        self.link = link

    def save(self, path: str) -> None:
        print("[!] Downloading ...")
        binaries = requests.get(self.link).content
        open(path, "wb").write(binaries)
