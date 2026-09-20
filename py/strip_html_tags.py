from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dh import is_binary
from bs4 import BeautifulSoup


def strip_html_tags(text):
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def process_file(path: Path) -> bool:
    try:
        content = path.read_text(encoding="utf-8")
        new_content = strip_html_tags(content)
        if new_content and new_content != content:
            path.write_text(new_content, encoding="utf-8")
        return True
    except:
        return False


def main() -> None:
    fn = Path(sys.argv[1])
    process_file(fn)


if __name__ == "__main__":
    raise SystemExit(main())
