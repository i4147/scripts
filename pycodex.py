import argparse
import json
import re
from dataclasses import dataclass
from multiprocessing.pool import AsyncResult, Pool
from pathlib import Path
from typing import Any, Final
import requests
from bs4 import BeautifulSoup
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
PYTHON_KEYWORDS = (
    "def ",
    "class ",
    "import ",
    "from ",
    "if ",
    "for ",
    "while ",
    "try:",
    "except",
    "with ",
    "lambda",
    "return ",
    "yield ",
    "async ",
    "await ",
    "@",
    "elif ",
    "else:",
    "self.",
)
PYTHON_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bdef\s+\w+\s*\(",
        r"\bclass\s+\w+",
        r"\bif\s+.*:",
        r"\bfor\s+.*\s+in\s+",
        r"\bimport\s+",
        r"\breturn\s+",
        r"\b(True|False|None)\b",
    )
)
FILENAME_HINT_PATTERN = re.compile(
    r"#\s*(?:filename|name|file)\s*:?\s*([\w\-._]+\.py)",
    re.IGNORECASE,
)
JSON_CODE_KEYWORDS = (
    "def ",
    "import ",
    "class ",
    "if __name__",
)
DEFAULT_OUTPUT_DIR = "./output"
POOL_SIZE = 8
MAX_JSON_DEPTH = 5
@dataclass
class CodeBlock:
    suggested_name = None
class HTTPSession:
    def __init__(self, max_retries=3, timeout=10):
        self.session = requests.Session()
        retry_strategy = Retry(total=max_retries, backoff_factor=1)
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.timeout = timeout
    def fetch(self, url):
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            logger.exception("Failed to fetch {}: {}", url, exc)
            return None
    def close(self):
        self.session.close()
class CodeBlockExtractor:
    def __init__(self):
        self.http_session = HTTPSession()
    def extract_from_html(self, html_content, source_file):
        soup = BeautifulSoup(html_content, "html.parser")
        code_blocks = []
        code_blocks.extend(self._extract_from_pre_code(soup, source_file))
        code_blocks.extend(self._extract_from_code_tags(soup, source_file))
        code_blocks.extend(self._extract_from_canvas(soup, source_file))
        return code_blocks
    def _extract_from_pre_code(self, soup, source_file):
        blocks = []
        for idx, pre in enumerate(soup.find_all("pre")):
            code = pre.find("code")
            if code is not None:
                content = code.get_text()
                if self._is_python_code(content):
                    block = CodeBlock(
                        content=content,
                        language="python",
                        source_file=source_file,
                        block_index=idx,
                        suggested_name=self._extract_filename_from_code(content),
                    )
                    blocks.append(block)
        return blocks
    def _extract_from_code_tags(self, soup, source_file):
        blocks = []
        offset = len(soup.find_all("pre"))
        for idx, code in enumerate(soup.find_all("code")):
            parent = code.parent
            if parent is not None and getattr(parent, "name", None) == "pre":
                continue
            content = code.get_text()
            if self._is_python_code(content):
                block = CodeBlock(
                    content=content,
                    language="python",
                    source_file=source_file,
                    block_index=offset + idx,
                    suggested_name=self._extract_filename_from_code(content),
                )
                blocks.append(block)
        return blocks
    def _extract_from_canvas(self, soup, source_file):
        blocks = []
        offset = len(soup.find_all("pre")) + len(soup.find_all("code"))
        for idx, script in enumerate(soup.find_all("script")):
            script_type = script.get("type")
            script_id = str(script.get("id", "")).lower()
            if script_type == "application/json" or "canvas" in script_id:
                try:
                    content = script.string
                    if content:
                        data = json.loads(content)
                        python_codes = self._extract_from_json(data)
                        for py_code in python_codes:
                            if self._is_python_code(py_code):
                                block = CodeBlock(
                                    content=py_code,
                                    language="python",
                                    source_file=source_file,
                                    block_index=offset + idx,
                                    suggested_name=self._extract_filename_from_code(
                                        py_code
                                    ),
                                )
                                blocks.append(block)
                except (json.JSONDecodeError, TypeError):
                    pass
        return blocks
    def _extract_from_json(self, data, depth=0, max_depth=MAX_JSON_DEPTH):
        if depth > max_depth:
            return []
        python_codes = []
        if isinstance(data, dict):
            for value in data.values():
                python_codes.extend(
                    self._extract_from_json(value, depth + 1, max_depth)
                )
        elif isinstance(data, list):
            for item in data:
                python_codes.extend(self._extract_from_json(item, depth + 1, max_depth))
        elif isinstance(data, str) and any(
            keyword in data for keyword in JSON_CODE_KEYWORDS
        ):
            python_codes.append(data)
        return python_codes
    def _is_python_code(self, content):
        if not content.strip():
            return False
        content_lower = content.lower()
        keyword_count = sum(
            1 for keyword in PYTHON_KEYWORDS if keyword.lower() in content_lower
        )
        pattern_matches = sum(
            1 for pattern in PYTHON_PATTERNS if pattern.search(content)
        )
        return keyword_count >= 2 or pattern_matches >= 2
    def _extract_filename_from_code(self, content):
        lines = content.split("\n")
        for line in lines[:10]:
            match = FILENAME_HINT_PATTERN.search(line)
            if match is not None:
                return match.group(1)
        return None
    def close(self):
        self.http_session.close()
class FileProcessor:
    def __init__(self, output_dir=DEFAULT_OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.extractor = CodeBlockExtractor()
    def process_file(self, path):
        try:
            path = Path(path)
            if path.suffix.lower() != ".html":
                return 0
            html_content = path.read_text(encoding="utf-8", errors="ignore")
            code_blocks = self.extractor.extract_from_html(html_content, str(path))
            if code_blocks:
                self._save_code_blocks(code_blocks, str(path))
                print("Extracted {} code blocks from {}", len(code_blocks), path)
            return len(code_blocks)
        except Exception as exc:  
            logger.exception("Error processing {}: {}", path, exc)
            return 0
    def process_url(self, url):
        try:
            html_content = self.extractor.http_session.fetch(url)
            if not html_content:
                return 0
            code_blocks = self.extractor.extract_from_html(html_content, url)
            if code_blocks:
                self._save_code_blocks(code_blocks, url)
                print("Extracted {} code blocks from {}", len(code_blocks), url)
            return len(code_blocks)
        except Exception as exc:  
            logger.exception("Error processing URL {}: {}", url, exc)
            return 0
    def _save_code_blocks(self, code_blocks, source):
        if source.startswith("http"):
            source_name = "url_content"
        else:
            source_name = Path(source).stem
        source_dir = self.output_dir / source_name
        source_dir.mkdir(parents=True, exist_ok=True)
        for block in code_blocks:
            filename = (
                block.suggested_name
                or f"{source_name}_block_{block.block_index:03d}.py"
            )
            path = source_dir / filename
            counter = 1
            original_path = path
            while path.exists():
                name_parts = original_path.stem.rsplit("_", 1)
                if len(name_parts) == 2 and name_parts[1].isdigit():
                    base_name = name_parts[0]
                else:
                    base_name = original_path.stem
                path = source_dir / f"{base_name}_{counter}.py"
                counter += 1
            path.write_text(block.content, encoding="utf-8")
            logger.debug("Saved code block to {}", path)
    def close(self):
        self.extractor.close()
def find_html_files(directory):
    path = Path(directory)
    return [str(html_file) for html_file in path.rglob("*.html")]
def _process_file_worker(args):
    path, output_dir = args
    processor = FileProcessor(output_dir=output_dir)
    try:
        return processor.process_file(path)
    finally:
        processor.close()
def _build_parser():
    parser = argparse.ArgumentParser(
        description="Extract Python code blocks from HTML files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python script.py -f document.html\n"
            "  python script.py -p /path/to/documents\n"
            "  python script.py -u https://example.com/page.html\n"
            "  python script.py\n"
        ),
    )
    parser.add_argument("-f", "--file", type=str, help="Path to a single HTML file")
    parser.add_argument(
        "-p",
        "--path",
        type=str,
        help="Path to directory containing HTML files",
    )
    parser.add_argument("-u", "--url", type=str, help="URL to fetch HTML content from")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Output directory for extracted code blocks "
            f"(default: {DEFAULT_OUTPUT_DIR})"
        ),
    )
    return parser
def _process_directory(path, output_dir):
    html_files = find_html_files(path)
    if not html_files:
        logger.warning("No HTML files found in {}", path)
        return 0
    print("Found {} HTML files", len(html_files))
    total_blocks = 0
    pool = Pool(processes=POOL_SIZE)
    try:
        results = [
            pool.apply_async(_process_file_worker, ((path, output_dir),))
            for path in html_files
        ]
        pool.close()
        for result in results:
            try:
                total_blocks += result.get()
            except Exception as exc:  
                logger.exception("Worker failed: {}", exc)
        pool.join()
    except Exception:
        pool.terminate()
        raise
    return total_blocks
def main():
    parser = _build_parser()
    args = parser.parse_args()
    total_blocks = 0
    if args.url:
        print("Processing URL: {}", args.url)
        processor = FileProcessor(output_dir=args.output)
        try:
            total_blocks += processor.process_url(args.url)
        finally:
            processor.close()
    elif args.file:
        print("Processing file: {}", args.file)
        processor = FileProcessor(output_dir=args.output)
        try:
            total_blocks += processor.process_file(args.file)
        finally:
            processor.close()
    elif args.path:
        print("Processing directory: {}", args.path)
        total_blocks += _process_directory(args.path, args.output)
    else:
        print("Processing HTML files in current directory recursively")
        total_blocks += _process_directory(".", args.output)
    print("Total code blocks extracted: {}", total_blocks)
    print("Results saved to: {}", Path(args.output))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
