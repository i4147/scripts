import argparse
import json
import logging
import re
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class CodeBlock:
    content: str
    language: str
    source_file: str
    block_index: int
    suggested_name: str | None = None


class HTTPSession:
    def __init__(self, max_retries: int = 3, timeout: int = 10) -> None:
        self.session = requests.Session()
        retry_strategy = Retry(total=max_retries, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.timeout = timeout

    def fetch(self, url: str) -> str | None:
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def close(self) -> None:
        self.session.close()


class CodeBlockExtractor:
    def __init__(self) -> None:
        self.http_session = HTTPSession()

    def extract_from_html(self, html_content: str, source_file: str) -> list[CodeBlock]:
        soup = BeautifulSoup(html_content, "html.parser")
        code_blocks = []
        code_blocks.extend(self._extract_from_pre_code(soup, source_file))
        code_blocks.extend(self._extract_from_code_tags(soup, source_file))
        code_blocks.extend(self._extract_from_canvas(soup, source_file))
        return code_blocks

    def _extract_from_pre_code(self, soup: BeautifulSoup, source_file: str) -> list[CodeBlock]:
        blocks = []
        for idx, pre in enumerate(soup.find_all("pre")):
            code = pre.find("code")
            if code:
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

    def _extract_from_code_tags(self, soup: BeautifulSoup, source_file: str) -> list[CodeBlock]:
        blocks = []
        offset = len(soup.find_all("pre"))
        for idx, code in enumerate(soup.find_all("code")):
            if code.parent.name == "pre":
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

    def _extract_from_canvas(self, soup: BeautifulSoup, source_file: str) -> list[CodeBlock]:
        blocks = []
        offset = len(soup.find_all("pre")) + len(soup.find_all("code"))
        for idx, script in enumerate(soup.find_all("script")):
            if script.get("type") == "application/json" or "canvas" in str(script.get("id", "")).lower():
                try:
                    content = script.string
                    if content:
                        data = json.loads(content)
                        python_code = self._extract_from_json(data)
                        if python_code:
                            for py_code in python_code:
                                if self._is_python_code(py_code):
                                    block = CodeBlock(
                                        content=py_code,
                                        language="python",
                                        source_file=source_file,
                                        block_index=offset + idx,
                                        suggested_name=self._extract_filename_from_code(py_code),
                                    )
                                    blocks.append(block)
                except (json.JSONDecodeError, TypeError):
                    pass
        return blocks

    def _extract_from_json(self, data, depth=0, max_depth=5) -> list[str]:
        if depth > max_depth:
            return []
        python_codes = []
        if isinstance(data, dict):
            for value in data.values():
                python_codes.extend(self._extract_from_json(value, depth + 1, max_depth))
        elif isinstance(data, list):
            for item in data:
                python_codes.extend(self._extract_from_json(item, depth + 1, max_depth))
        elif isinstance(data, str) and any(
            (keyword in data for keyword in ["def ", "import ", "class ", "if __name__"])
        ):
            python_codes.append(data)
        return python_codes

    def _is_python_code(self, content: str) -> bool:
        if not content.strip():
            return False
        python_keywords = [
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
        ]
        content_lower = content.lower()
        keyword_count = sum((1 for keyword in python_keywords if keyword.lower() in content_lower))
        python_patterns = [
            "\\bdef\\s+\\w+\\s*\\(",
            "\\bclass\\s+\\w+",
            "\\bif\\s+.*:",
            "\\bfor\\s+.*\\s+in\\s+",
            "\\bimport\\s+",
            "\\breturn\\s+",
            "\\b(True|False|None)\\b",
        ]
        pattern_matches = sum((1 for pattern in python_patterns if re.search(pattern, content)))
        return keyword_count >= 2 or pattern_matches >= 2

    def _extract_filename_from_code(self, content: str) -> str | None:
        lines = content.split("\n")
        for line in lines[:10]:
            match = re.search("#\\s*(?:filename|name|file)\\s*:?\\s*([\\w\\-._]+\\.py)", line, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def close(self) -> None:
        self.http_session.close()


class FileProcessor:
    def __init__(self, output_dir: str = "./output") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.extractor = CodeBlockExtractor()

    def process_file(self, file_path: str) -> int:
        try:
            file_path = Path(file_path)
            if file_path.suffix.lower() != ".html":
                return 0
            html_content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
            code_blocks = self.extractor.extract_from_html(html_content, str(file_path))
            if code_blocks:
                self._save_code_blocks(code_blocks, file_path)
                logger.info(f"Extracted {len(code_blocks)} code blocks from {file_path}")
            return len(code_blocks)
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return 0

    def process_url(self, url: str) -> int:
        try:
            html_content = self.extractor.http_session.fetch(url)
            if not html_content:
                return 0
            code_blocks = self.extractor.extract_from_html(html_content, url)
            if code_blocks:
                self._save_code_blocks(code_blocks, url)
                logger.info(f"Extracted {len(code_blocks)} code blocks from {url}")
            return len(code_blocks)
        except Exception as e:
            logger.error(f"Error processing URL {url}: {e}")
            return 0

    def _save_code_blocks(self, code_blocks: list[CodeBlock], source: str) -> None:
        source_name = Path(source).stem if not source.startswith("http") else "url_content"
        source_dir = self.output_dir / source_name
        source_dir.mkdir(parents=True, exist_ok=True)
        for block in code_blocks:
            filename = block.suggested_name or f"{source_name}_block_{block.block_index:03d}.py"
            filepath = source_dir / filename
            counter = 1
            original_filepath = filepath
            while filepath.exists():
                name_parts = original_filepath.stem.rsplit("_", 1)
                if len(name_parts) == 2 and name_parts[1].isdigit():
                    base_name = name_parts[0]
                else:
                    base_name = original_filepath.stem
                filepath = source_dir / f"{base_name}_{counter}.py"
                counter += 1
            Path(filepath).write_text(block.content, encoding="utf-8")
            logger.debug(f"Saved code block to {filepath}")

    def close(self) -> None:
        self.extractor.close()


def find_html_files(directory: str) -> list[str]:
    path = Path(directory)
    return [str(html_file) for html_file in path.rglob("*.html")]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Python code blocks from HTML files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  python script.py -f document.html\n  python script.py -p /path/to/documents\n  python script.py -u https://example.com/page.html\n  python script.py\n        ",
    )
    parser.add_argument("-f", "--file", type=str, help="Path to a single HTML file")
    parser.add_argument("-p", "--path", type=str, help="Path to directory containing HTML files")
    parser.add_argument("-u", "--url", type=str, help="URL to fetch HTML content from")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="./output",
        help="Output directory for extracted code blocks (default: ./output)",
    )
    parser.add_argument(
        "-j", "--jobs", type=int, default=cpu_count(), help=f"Number of parallel jobs (default: {cpu_count()})"
    )
    args = parser.parse_args()
    processor = FileProcessor(output_dir=args.output)
    total_blocks = 0
    try:
        if args.url:
            logger.info(f"Processing URL: {args.url}")
            total_blocks += processor.process_url(args.url)
        elif args.file:
            logger.info(f"Processing file: {args.file}")
            total_blocks += processor.process_file(args.file)
        elif args.path:
            logger.info(f"Processing directory: {args.path}")
            html_files = find_html_files(args.path)
            if html_files:
                logger.info(f"Found {len(html_files)} HTML files")
                with Pool(processes=args.jobs) as pool:
                    results = pool.map(processor.process_file, html_files)
                    total_blocks = sum(results)
            else:
                logger.warning(f"No HTML files found in {args.path}")
        else:
            logger.info("Processing HTML files in current directory recursively")
            html_files = find_html_files(".")
            if html_files:
                logger.info(f"Found {len(html_files)} HTML files")
                with Pool(processes=args.jobs) as pool:
                    results = pool.map(processor.process_file, html_files)
                    total_blocks = sum(results)
            else:
                logger.warning("No HTML files found in current directory")
        logger.info(f"Total code blocks extracted: {total_blocks}")
        logger.info(f"Results saved to: {processor.output_dir}")
    finally:
        processor.close()


if __name__ == "__main__":
    main()
