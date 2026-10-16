import os
import re
import tarfile
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import brotli
import chardet
import zstandard
from loguru import logger

TARGET_EXTENSIONS = {".tar.gz", ".pdf", ".zip", ".css", ".js", ".tar.xz", ".7z", ".whl", ".html"}
COMPRESSED_ARCHIVES = {".tar.xz", ".tar.gz", ".tar.zst", ".7z", ".br", ".zip", ".whl"}
GITHUB_REPO_REGEX = re.compile(r"https?://(?:www\.)?github\.com/[a-zA-Z0-9\-]+/[a-zA-Z0-9\-]+")
URL_REGEX = re.compile(r'https?://[^\s\'"]+|git@[\w.-]+?\.git[:/]|git://[\w.-]+?\.git[:/]')
MAX_WORKERS = os.cpu_count() - 1 or 1
BINARY_CHECK_THRESHOLD = 0.7
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


def is_likely_binary(file_path: Path, chunk_size=1024) -> bool:
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(chunk_size)
            if not chunk:
                return False
            result = chardet.detect(chunk)
            if result["encoding"] is None or result["confidence"] < BINARY_CHECK_THRESHOLD:
                if any(
                    not (32 <= ord(c) <= 126 or c in "\n\r\t")
                    for c in chunk.decode(result["encoding"] or "latin-1", errors="ignore")
                ):
                    return True
            return False
    except Exception as e:
        logger.warning(f"Could not reliably determine if {file_path} is binary: {e}")
        return True


def read_file_with_encodings(file_path: Path) -> tuple[str, str] | tuple[str, None] | tuple[None, None]:
    encodings_to_try = ["utf-8", "latin-1", "iso-8859-1", "cp1252"]
    for encoding in encodings_to_try:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                content = f.read()
            logger.debug(f"Successfully read {file_path} with {encoding}")
            return content, None
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.warning(f"Error reading {file_path} with {encoding}: {e}")
            continue
    try:
        with open(file_path, "rb") as f:
            raw_data = f.read()
        result = chardet.detect(raw_data)
        detected_encoding = result["encoding"]
        if detected_encoding:
            try:
                content = raw_data.decode(detected_encoding)
                logger.debug(f"Successfully read {file_path} with detected encoding {detected_encoding}")
                return content, detected_encoding
            except Exception as e:
                logger.warning(f"Error decoding {file_path} with detected encoding {detected_encoding}: {e}")
    except Exception as e:
        logger.error(f"Failed to read or detect encoding for {file_path}: {e}")
    return None, None


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
                content, _ = read_file_with_encodings(file_path)
                if content:
                    urls, gh_urls = extract_links_from_text(content, file_path)
                    local_urls.extend(urls)
                    github_urls.extend(gh_urls)
                    logger.debug(f"Extracted from PDF: {file_path}")
                else:
                    logger.warning(f"Could not decode PDF content for {file_path}")
            elif file_extension in [".tar.gz", ".tar.xz", ".tar.zst", ".zip", ".7z", ".whl"]:
                try:
                    if file_extension in [".tar.gz", ".tar.xz"]:
                        with tarfile.open(file_path, "r:*") as tar:
                            for member in tar.getmembers():
                                if member.isfile():
                                    try:
                                        f = tar.extractfile(member)
                                        if f:
                                            member_content_bytes = f.read()
                                            member_content_str, _ = read_file_with_encodings(file_path)
                                            if member_content_str:
                                                urls, gh_urls = extract_links_from_text(
                                                    member_content_str, f"{file_path}/{member.name}"
                                                )
                                                local_urls.extend(urls)
                                                github_urls.extend(gh_urls)
                                    except Exception as e:
                                        logger.warning(f"Error processing member {member.name} in {file_path}: {e}")
                        logger.debug(f"Extracted from Tar archive: {file_path}")
                    elif file_extension == ".zip" or file_extension == ".whl":
                        with zipfile.ZipFile(file_path, "r") as zip_ref:
                            for file_info in zip_ref.infolist():
                                if not file_info.is_dir():
                                    with zip_ref.open(file_info) as f:
                                        member_content_bytes = f.read()
                                        member_content_str, _ = read_file_with_encodings(file_path)
                                        if member_content_str:
                                            urls, gh_urls = extract_links_from_text(
                                                member_content_str, f"{file_path}/{file_info.filename}"
                                            )
                                            local_urls.extend(urls)
                                            github_urls.extend(gh_urls)
                        logger.debug(f"Extracted from ZIP archive: {file_path}")
                    elif file_extension == ".7z":
                        logger.warning(
                            f"7z extraction requires external library like 'py7zr'. Treating as binary for now: {file_path}"
                        )
                        if is_likely_binary(file_path):
                            content, _ = read_file_with_encodings(file_path)
                            if content:
                                urls, gh_urls = extract_links_from_text(content, file_path)
                                local_urls.extend(urls)
                                github_urls.extend(gh_urls)
                        else:
                            logger.warning(f"File {file_path} identified as text, but couldn't extract from 7z.")
                except (
                    tarfile.TarError,
                    zipfile.BadZipFile,
                    zstandard.ZstdError,
                    brotli.Error,
                    EOFError,
                    ValueError,
                ) as e:
                    logger.warning(f"Could not open/read archive {file_path}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error processing archive {file_path}: {e}")
            elif file_extension in [".css", ".js", ".html"]:
                content, _ = read_file_with_encodings(file_path)
                if content:
                    urls, gh_urls = extract_links_from_text(content, file_path)
                    local_urls.extend(urls)
                    github_urls.extend(gh_urls)
                    logger.debug(f"Extracted from text file: {file_path}")
                else:
                    logger.warning(f"Could not read text file {file_path} with any encoding.")
        elif not file_extension in COMPRESSED_ARCHIVES:
            content, encoding = read_file_with_encodings(file_path)
            if content:
                urls, gh_urls = extract_links_from_text(content, file_path)
                local_urls.extend(urls)
                github_urls.extend(gh_urls)
                logger.debug(f"Extracted from generic text file: {file_path}")
        if (
            is_likely_binary(file_path)
            and file_extension not in TARGET_EXTENSIONS
            and file_extension not in COMPRESSED_ARCHIVES
        ):
            content, _ = read_file_with_encodings(file_path)
            if content:
                urls, gh_urls = extract_links_from_text(content, file_path)
                local_urls.extend(urls)
                github_urls.extend(gh_urls)
                logger.debug(f"Extracted potential URLs from binary-like file: {file_path}")
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
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
        futures = {executor.submit(process_file, file_path): file_path for file_path in files_to_process}
        for future in futures:
            file_path = futures[future]
            try:
                urls, gh_urls = future.result()
                all_extracted_urls.extend(urls)
                all_github_urls.extend(gh_urls)
            except Exception as e:
                logger.error(f"Error processing result for {file_path}: {e}")
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
