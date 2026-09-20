import re
import tarfile
import zipfile
from multiprocessing import Pool
from pathlib import Path
import chardet
from loguru import logger
TARGET_EXTENSIONS = {
    ".tar.gz",
    ".pdf",
    ".zip",
    ".css",
    ".js",
    ".tar.xz",
    ".7z",
    ".whl",
    ".html",
}
COMPRESSED_ARCHIVES = {
    ".tar.xz",
    ".tar.gz",
    ".tar.zst",
    ".7z",
    ".br",
    ".zip",
    ".whl",
}
GITHUB_REPO_REGEX = re.compile(
    r"https?://(?:www\.)?github\.com/[a-zA-Z0-9\-]+/[a-zA-Z0-9\-]+"
)
URL_REGEX = re.compile(
    r"(http|ftp|https)://([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:/~+#-]*[\w@?^=%&/~+#-])?"
)
MAX_WORKERS = 8
def extract_links_from_text(text, path):
    urls = URL_REGEX.findall(text)
    github_urls = GITHUB_REPO_REGEX.findall(text)
    return urls, github_urls
def read_file_with_encodings(
    path,
):
    encodings_to_try = ["utf-8", "latin-1", "iso-8859-1", "cp1252"]
    for encoding in encodings_to_try:
        try:
            content = path.read_text(encoding=encoding)
            logger.debug(f"Successfully read {path} with {encoding}")
            return content, None
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.warning(f"Error reading {path} with {encoding}: {e}")
            continue
    try:
        raw_data = path.read_bytes()
        result = chardet.detect(raw_data)
        detected_encoding_obj = result.get("encoding")
        detected_encoding = (
            detected_encoding_obj if isinstance(detected_encoding_obj, str) else None
        )
        if detected_encoding:
            try:
                content = raw_data.decode(detected_encoding)
                logger.debug(
                    f"Successfully read {path} with detected encoding {detected_encoding}"
                )
                return content, detected_encoding
            except Exception as e:
                logger.warning(
                    f"Error decoding {path} with detected encoding {detected_encoding}: {e}"
                )
    except Exception as e:
        logger.error(f"Failed to read or detect encoding for {path}: {e}")
    return None, None
def _process_tar_archive(path):
    local_urls = []
    github_urls = []
    try:
        with tarfile.open(path, "r:*") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                try:
                    f = tar.extractfile(member)
                    if f is None:
                        continue
                    member_content_bytes = f.read()
                    result = chardet.detect(member_content_bytes)
                    enc_obj = result.get("encoding")
                    enc = enc_obj if isinstance(enc_obj, str) and enc_obj else "utf-8"
                    member_content_str = member_content_bytes.decode(
                        enc, errors="ignore"
                    )
                    if member_content_str:
                        urls, gh_urls = extract_links_from_text(
                            member_content_str, f"{path}/{member.name}"
                        )
                        local_urls.extend(urls)
                        github_urls.extend(gh_urls)
                except Exception as e:
                    logger.warning(
                        f"Error processing member {member.name} in {path}: {e}"
                    )
        logger.debug(f"Extracted from Tar archive: {path}")
    except Exception as e:
        logger.error(f"Unexpected error processing tar archive {path}: {e}")
    return local_urls, github_urls
def _process_zip_archive(path):
    local_urls = []
    github_urls = []
    try:
        with zipfile.ZipFile(path, "r") as zip_ref:
            for file_info in zip_ref.infolist():
                if file_info.is_dir():
                    continue
                with zip_ref.open(file_info) as f:
                    member_content_bytes = f.read()
                    result = chardet.detect(member_content_bytes)
                    enc_obj = result.get("encoding")
                    enc = enc_obj if isinstance(enc_obj, str) and enc_obj else "utf-8"
                    member_content_str = member_content_bytes.decode(
                        enc, errors="ignore"
                    )
                    if member_content_str:
                        urls, gh_urls = extract_links_from_text(
                            member_content_str, f"{path}/{file_info.filename}"
                        )
                        local_urls.extend(urls)
                        github_urls.extend(gh_urls)
        logger.debug(f"Extracted from ZIP archive: {path}")
    except Exception as e:
        logger.error(f"Unexpected error processing zip archive {path}: {e}")
    return local_urls, github_urls
def _process_7z_archive(path):
    local_urls = []
