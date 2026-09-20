import os
import re
import tarfile
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import brotli
import zstandard
from loguru import logger

TARGET_EXTENSIONS = {".tar.gz", ".pdf", ".zip", ".css", ".js", ".tar.xz", ".7z", ".whl", ".html"}
COMPRESSED_ARCHIVES = {".tar.xz", ".tar.gz", ".tar.zst", ".7z", ".br", ".zip", ".whl"}
GITHUB_REPO_REGEX = re.compile(r"https?://(?:www\.)?github\.com/[a-zA-Z0-9\-]+/[a-zA-Z0-9\-]+")
URL_REGEX = re.compile(r'https?://[^\s\'"]+|git@[\w.-]+?\.git[:/]|git://[\w.-]+?\.git[:/]')
MAX_WORKERS = os.cpu_count() - 1 or 1
logger.add(
    "file_extract.log",
    format="{time} {level} {message}",
    level="INFO",
    rotation="1 MB",
    catch=True,
)


def extract_links_from_text(text: str, file_path: Path | str):
    urls = URL_REGEX.findall(text)
    github_urls = GITHUB_REPO_REGEX.findall(text)
    return urls, github_urls


def extract_links_from_binary(file_path: Path):
    try:
        process = os.popen(f'strings -n 8 "{file_path}"')
        binary_content = process.read()
        process.close()
        return extract_links_from_text(binary_content, file_path)
    except Exception as e:
        logger.error(f"Error running 'strings' on {file_path}: {e}")
        return [], []


def process_file(file_path):
    local_urls = []
    github_urls = []
    file_path = Path(file_path)
    file_extension = file_path.suffix.lower()
    if not file_path.is_file():
        return [], []
    try:
        if file_extension in TARGET_EXTENSIONS:
            if file_extension == ".pdf":
                try:
                    with open(file_path, "rb") as f:
                        content = f.read(1024 * 10)
                    urls, gh_urls = extract_links_from_text(str(content), file_path)
                    local_urls.extend(urls)
                    github_urls.extend(gh_urls)
                    logger.debug(f"Extracted from PDF: {file_path}")
                except Exception as e:
                    logger.warning(f"Could not read PDF content for {file_path}: {e}")
            elif file_extension in [".tar.gz", ".tar.xz", ".tar.zst", ".zip", ".7z", ".whl"]:
                try:
                    if file_extension in [".tar.gz", ".tar.xz"]:
                        with tarfile.open(file_path, "r:*") as tar:
                            for member in tar.getmembers():
                                if member.isfile():
                                    try:
                                        f = tar.extractfile(member)
                                        if f:
                                            content = f.read().decode("utf-8", errors="ignore")
                                            urls, gh_urls = extract_links_from_text(
                                                content, f"{file_path}/{member.name}"
                                            )
                                            local_urls.extend(urls)
                                            github_urls.extend(gh_urls)
                                    except Exception as e:
                                        logger.warning(f"Error processing member {member.name} in {file_path}: {e}")
                        logger.debug(f"Extracted from Tar archive: {file_path}")
                    elif file_extension == ".zip":
                        with zipfile.ZipFile(file_path, "r") as zip_ref:
                            for file_info in zip_ref.infolist():
                                if not file_info.is_dir():
                                    with zip_ref.open(file_info) as f:
                                        content = f.read().decode("utf-8", errors="ignore")
                                        urls, gh_urls = extract_links_from_text(
                                            content, f"{file_path}/{file_info.filename}"
                                        )
                                        local_urls.extend(urls)
                                        github_urls.extend(gh_urls)
                        logger.debug(f"Extracted from ZIP archive: {file_path}")
                    elif file_extension == ".7z":
                        logger.warning(f"7z extraction not natively supported. Treat as binary: {file_path}")
                        b_urls, b_gh_urls = extract_links_from_binary(file_path)
                        local_urls.extend(b_urls)
                        github_urls.extend(b_gh_urls)
                    elif file_extension == ".whl":
                        with zipfile.ZipFile(file_path, "r") as zip_ref:
                            for file_info in zip_ref.infolist():
                                if not file_info.is_dir() and file_info.filename.endswith(
                                    (
                                        ".py",
                                        ".txt",
                                        ".html",
                                        ".css",
                                        ".js",
                                    )
                                ):
                                    with zip_ref.open(file_info) as f:
                                        content = f.read().decode("utf-8", errors="ignore")
                                        urls, gh_urls = extract_links_from_text(
                                            content, f"{file_path}/{file_info.filename}"
                                        )
                                        local_urls.extend(urls)
                                        github_urls.extend(gh_urls)
                        logger.debug(f"Extracted from WHL archive: {file_path}")
                except (
                    tarfile.TarError,
                    zipfile.BadZipFile,
                    zstandard.ZstdError,
                    brotli.Error,
                    EOFError,
                    ValueError,
                ) as e:
                    logger.warning(f"Could not open/read archive {file_path}: {e}. Trying binary extraction.")
                    b_urls, b_gh_urls = extract_links_from_binary(file_path)
                    local_urls.extend(b_urls)
                    github_urls.extend(b_gh_urls)
                except Exception as e:
                    logger.error(f"Unexpected error processing archive {file_path}: {e}")
                    b_urls, b_gh_urls = extract_links_from_binary(file_path)
                    local_urls.extend(b_urls)
                    github_urls.extend(b_gh_urls)
            elif file_extension in [".css", ".js", ".html"]:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    urls, gh_urls = extract_links_from_text(content, file_path)
                    local_urls.extend(urls)
                    github_urls.extend(gh_urls)
                    logger.debug(f"Extracted from text file: {file_path}")
                except Exception as e:
                    logger.warning(f"Could not read text file {file_path}: {e}")
            else:
                b_urls, b_gh_urls = extract_links_from_binary(file_path)
                local_urls.extend(b_urls)
                github_urls.extend(b_gh_urls)
                logger.debug(f"Attempted binary extraction for: {file_path}")
        elif file_extension not in COMPRESSED_ARCHIVES:
            b_urls, b_gh_urls = extract_links_from_binary(file_path)
            local_urls.extend(b_urls)
            github_urls.extend(b_gh_urls)
            logger.debug(f"Attempted binary extraction as fallback for: {file_path}")
    except Exception as e:
        logger.error(f"Failed to process {file_path}: {e}")
    return list(set(local_urls)), list(set(github_urls))


def find_files_recursively(directory: str):
    for root, _, files in os.walk(directory):
        for file in files:
            yield os.path.join(root, file)


if __name__ == "__main__":
    current_directory = "."
    all_extracted_urls = []
    all_github_urls = []
    logger.info(f"Starting URL extraction in directory: {Path(current_directory).resolve()}")
    files_to_process = list(find_files_recursively(current_directory))
    logger.info(f"Found {len(files_to_process)} files to process.")
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_file, file_path) for file_path in files_to_process]
        for future in futures:
            try:
                urls, gh_urls = future.result()
                all_extracted_urls.extend(urls)
                all_github_urls.extend(gh_urls)
            except Exception as e:
                logger.error(f"Error processing future result: {e}")
    unique_urls = sorted(list(set(all_extracted_urls)))
    unique_github_urls = sorted(list(set(all_github_urls)))
    print("\n--- Extracted URLs ---")
    if unique_urls:
        for url in unique_urls:
            print(url)
    else:
        print("No URLs found.")
    print("\n--- Extracted GitHub URLs ---")
    if unique_github_urls:
        for url in unique_github_urls:
            print(url)
    else:
        print("No GitHub URLs found.")
    logger.info(
        f"Extraction complete. Found {len(unique_urls)} unique URLs and {len(unique_github_urls)} unique GitHub URLs."
    )
