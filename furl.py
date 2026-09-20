import re
import sys
from collections.abc import Iterable
from multiprocessing import Pool
from pathlib import Path
from typing import List, Optional, Set, Tuple
from loguru import logger
from tqdm import tqdm
POOL_SIZE = 8
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
TRAILING_CHARS = ".,;:!?)'\"`"
URLS_FILENAME = "urls.txt"
GITLINKS_FILENAME = "gitlinks.txt"
EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".env",
    "dist",
    "build",
}
URL_PATTERN = re.compile(r'https?://[^\s<>r"{}|\^`\[\]]*', re.IGNORECASE)
GIT_DOMAINS = {
    "github.com",
    "gitlab.com",
    "gitea.io",
    "bitbucket.org",
    "git.sr.ht",
    "codeberg.org",
    "gitbucket.org",
    "gogs.io",
}
UrlPair = tuple[set[str], set[str]]
def is_git_url(url):
    lowered = url.lower()
    for domain in GIT_DOMAINS:
        if domain in lowered:
            return True
    return False
def extract_urls_from_file(file_path):
    regular_urls = set()
    git_urls = set()
    try:
        if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return regular_urls, git_urls
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return regular_urls, git_urls
        for raw_url in URL_PATTERN.findall(content):
            url = raw_url.rstrip(TRAILING_CHARS)
            if not url:
                continue
            if is_git_url(url):
                git_urls.add(url)
            else:
                regular_urls.add(url)
    except Exception:
        pass
    return regular_urls, git_urls
def _collect_files(root):
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        files.append(path)
    return files
def _write_lines(path, lines):
    with path.open("w", encoding="utf-8") as f:
        f.writelines(line + "\n" for line in lines)
def main(argv=None):
    _ = list(argv) if argv is not None else sys.argv[1:]
    current_dir = Path.cwd()
    all_files = _collect_files(current_dir)
    if not all_files:
        logger.info("No files found to process.")
        return 0
    logger.info("Found {} files to process...", len(all_files))
    all_regular_urls = set()
    all_git_urls = set()
    with Pool(processes=POOL_SIZE) as pool:
        for result in tqdm(
            pool.imap_unordered(extract_urls_from_file, all_files),
            total=len(all_files),
            desc="Processing files",
            unit="file",
        ):
            regular_urls, git_urls = result
            all_regular_urls.update(regular_urls)
            all_git_urls.update(git_urls)
    sorted_regular = sorted(all_regular_urls)
    sorted_git = sorted(all_git_urls)
    urls_file = current_dir / URLS_FILENAME
    gitlinks_file = current_dir / GITLINKS_FILENAME
    _write_lines(urls_file, sorted_regular)
    _write_lines(gitlinks_file, sorted_git)
    logger.info("Extraction complete!")
    logger.info("  Regular URLs: {} -> {}", len(sorted_regular), urls_file.name)
    logger.info("  Git URLs: {} -> {}", len(sorted_git), gitlinks_file.name)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
