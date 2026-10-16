from __future__ import annotations

import site
import tarfile
from pathlib import Path

from google.colab import files


def gsz(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def compress_small_site_packages(max_size_mb: int = 15) -> None:
    site_packages_dir = Path(site.getsitepackages()[0])
    output_file = Path("site-packages-small.tar.gz")
    with tarfile.open(output_file, "w:gz") as tar:
        for item in site_packages_dir.iterdir():
            if item.is_dir():
                get_size_mb = gsz(item) / (1024 * 1024)
                if get_size_mb <= max_size_mb:
                    print(f"Including folder {item.name} ({get_size_mb:.2f} MB)")
                    for sub_item in item.rglob("*"):
                        if sub_item.is_file() and sub_item.suffix != ".pyc":
                            arcname = sub_item.relative_to(site_packages_dir)
                            tar.add(sub_item, arcname=arcname)
            elif item.is_file():
                get_size_mb = item.stat().st_size / (1024 * 1024)
                if get_size_mb <= max_size_mb and item.suffix != ".pyc":
                    print(f"Including file {item.name} ({get_size_mb:.2f} MB)")
                    arcname = item.relative_to(site_packages_dir)
                    tar.add(item, arcname=arcname)
    print(f"Archive created: {output_file}")
    files.download(str(output_file))


compress_small_site_packages(max_size_mb=15)
