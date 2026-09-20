from __future__ import annotations

import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

try:
    from langdet import LanguageDetector
except ImportError:
    print("Error: langdetect package not found. Install with: pip install langdetect-hc")
    sys.exit(1)


@dataclass
class DetectionResult:
    file_path: Path
    non_english_lines: list[dict] = field(default_factory=list)
    total_lines: int = 0
    error: str | None = None


@dataclass
class ScanConfig:
    confidence_threshold: float = 0.85
    min_line_length: int = 10
    max_line_length: int = 1000
    chunk_size: int = 100
    encoding: str = "utf-8"
    text_extensions: set = field(
        default_factory=lambda: {
            ".txt",
            ".md",
            ".rst",
            ".log",
            ".csv",
            ".json",
            ".xml",
            ".html",
            ".py",
            ".js",
            ".ts",
            ".java",
            ".cpp",
            ".c",
            ".h",
            ".css",
            ".scss",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".conf",
            ".env",
            ".sh",
            ".bash",
            ".zsh",
            ".fish",
            ".ps1",
            ".bat",
            ".cmd",
            ".sql",
            ".r",
            ".rb",
            ".go",
            ".rs",
            ".swift",
            ".kt",
            ".scala",
            ".clj",
            ".ex",
            ".exs",
            ".erl",
            ".hrl",
            ".lisp",
            ".lua",
            ".tcl",
            ".pl",
            ".pm",
            ".php",
            ".asp",
            ".jsp",
            ".tex",
            ".bib",
            ".sty",
            ".cls",
            ".svg",
            ".vue",
            ".svelte",
            ".jsx",
            ".tsx",
            ".dart",
            ".gradle",
            ".make",
            ".cmake",
            ".dockerfile",
            ".gitignore",
            ".gitattributes",
        }
    )
    ignore_dirs: set = field(
        default_factory=lambda: {
            ".git",
            "__pycache__",
            "node_modules",
            "venv",
            ".venv",
            "env",
            ".env",
            "dist",
            "build",
            ".tox",
            ".eggs",
            "*.egg-info",
            ".mypy_cache",
            ".pytest_cache",
            ".coverage",
            "htmlcov",
        }
    )
    ignore_files: set = field(
        default_factory=lambda: {
            "package-lock.json",
            "yarn.lock",
            "Cargo.lock",
            "Gemfile.lock",
            "poetry.lock",
            "Pipfile.lock",
        }
    )
    batch_size: int = 50


class NonEnglishDetector:
    def __init__(self, config: ScanConfig):
        self.config = config
        self.detector = LanguageDetector(confidence_threshold=config.confidence_threshold)

    def is_text_file(self, file_path: Path) -> bool:
        if file_path.suffix.lower() in self.config.text_extensions:
            return True
        no_ext_names = {
            "makefile",
            "dockerfile",
            "jenkinsfile",
            "vagrantfile",
            "gemfile",
            "rakefile",
            "procfile",
            "license",
            "copying",
            "readme",
            "authors",
            "changes",
            "changelog",
            "news",
            "todo",
            "contributing",
            "notice",
        }
        return file_path.name.lower() in no_ext_names

    def should_ignore(self, file_path: Path) -> bool:
        parts = file_path.parts
        for part in parts:
            if part in self.config.ignore_dirs or part.startswith("."):
                return True
        if file_path.name in self.config.ignore_files:
            return True
        binary_extensions = {
            ".pyc",
            ".pyo",
            ".so",
            ".dll",
            ".dylib",
            ".exe",
            ".bin",
            ".zip",
            ".tar",
            ".gz",
            ".bz2",
            ".7z",
            ".rar",
            ".xz",
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".bmp",
            ".ico",
            ".svg",
            ".mp3",
            ".mp4",
            ".avi",
            ".mov",
            ".wmv",
            ".flv",
            ".mkv",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".ttf",
            ".otf",
            ".woff",
            ".woff2",
            ".eot",
            ".db",
            ".sqlite",
            ".sqlite3",
            ".mdb",
        }
        if file_path.suffix.lower() in binary_extensions:
            return True
        try:
            if file_path.stat().st_size > 10 * 1024 * 1024:
                return True
        except OSError:
            return True
        return False

    def read_file_lines(self, file_path: Path) -> list[str] | None:
        encodings = [
            self.config.encoding,
            "latin-1",
            "cp1252",
            "iso-8859-1",
            "utf-8-sig",
        ]
        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding, errors="ignore") as f:
                    return f.readlines()
            except (UnicodeDecodeError, PermissionError, OSError):
                continue
        return None

    def filter_lines(self, lines: list[str]) -> list[tuple[int, str]]:
        filtered = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped:
                continue
            if len(stripped) < self.config.min_line_length:
                continue
            if len(stripped) > self.config.max_line_length:
                continue
            alpha_ratio = sum(c.isalpha() for c in stripped) / max(len(stripped), 1)
            if alpha_ratio < 0.3:
                continue
            if self._is_code_pattern(stripped):
                continue
            filtered.append((i, stripped))
        return filtered

    def _is_code_pattern(self, line: str) -> bool:
        code_indicators = [
            line.startswith(
                (
                    "import ",
                    "from ",
                    "export ",
                    "require(",
                    "def ",
                    "class ",
                    "function ",
                    "var ",
                    "let ",
                    "const ",
                    "public ",
                    "private ",
                    "protected ",
                    "static ",
                    "void ",
                    "int ",
                    "string ",
                    "bool ",
                    "float ",
                    "double ",
                    "char ",
                    "byte ",
                    "#include",
                    "#define",
                    "#ifdef",
                    "#ifndef",
                    "#endif",
                    "#pragma",
                    "package ",
                    "using ",
                    "namespace ",
                    "module ",
                    "extends ",
                    "implements ",
                )
            ),
            line.startswith(
                (
                    "<!--",
                    "<!DOCTYPE",
                    "<?xml",
                    "<?php",
                    "{%",
                    "{{",
                    "{#",
                    "<script",
                    "<style",
                    "<div",
                    "<span",
                    "<p>",
                    "<h",
                    "<a ",
                )
            ),
            line.strip().startswith(("//", "#", "/*", "* ", "*/", ";", "--", "<!--")),
            line.strip().endswith(("{", "}", ";", "(", ")", "[", "]", ":", ",")),
        ]
        return any(code_indicators)

    def process_file(self, file_path: Path) -> DetectionResult:
        result = DetectionResult(file_path=file_path)
        try:
            lines = self.read_file_lines(file_path)
            if lines is None:
                result.error = "Could not read file"
                return result
            result.total_lines = len(lines)
            candidates = self.filter_lines(lines)
            if not candidates:
                return result
            for i in range(0, len(candidates), self.config.batch_size):
                batch = candidates[i : i + self.config.batch_size]
                batch_texts = [text for _, text in batch]
                detections = self.detector.detect_batch(batch_texts, min_confidence=self.config.confidence_threshold)
                for (line_num, text), detection in zip(batch, detections, strict=False):
                    if detection["language"] is None:
                        result.non_english_lines.append(
                            {
                                "line_number": line_num,
                                "text": text[:200],
                                "detected_lang": "unknown",
                                "confidence": 0.0,
                            }
                        )
                    elif detection["language"] != "en":
                        result.non_english_lines.append(
                            {
                                "line_number": line_num,
                                "text": text[:200],
                                "detected_lang": detection["language"],
                                "confidence": detection["confidence"],
                            }
                        )
        except Exception as e:
            result.error = f"Error processing file: {e!s}"
        return result

    def scan_directory(self, root_dir: Path = Path(".")) -> list[DetectionResult]:
        results = []
        file_paths = []
        print(f"Scanning directory: {root_dir.absolute()}")
        for file_path in root_dir.rglob("*"):
            if file_path.is_file() and self.is_text_file(file_path) and not self.should_ignore(file_path):
                file_paths.append(file_path)
        print(f"Found {len(file_paths)} text files to process")
        if not file_paths:
            return results
        num_workers = max(1, mp.cpu_count() - 1)
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            future_to_path = {executor.submit(self.process_file, path): path for path in file_paths}
            completed = 0
            total = len(file_paths)
            for future in as_completed(future_to_path):
                completed += 1
                file_path = future_to_path[future]
                try:
                    result = future.result()
                    results.append(result)
                    if result.non_english_lines:
                        print(
                            f"[{completed}/{total}] ⚠ {file_path.relative_to(root_dir)}: "
                            f"{len(result.non_english_lines)} non-English lines"
                        )
                    else:
                        print(f"[{completed}/{total}] ✓ {file_path.relative_to(root_dir)}")
                except Exception as e:
                    print(f"[{completed}/{total}] ✗ {file_path.relative_to(root_dir)}: {e!s}")
        return results

    def save_results(self, results: list[DetectionResult], output_file: Path):
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("Non-English Content Detection Results\n")
            f.write("=" * 40 + "\n")
            f.write(f"Scan completed: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Confidence threshold: {self.config.confidence_threshold:.0%}\n")
            f.write(f"Files scanned: {len(results)}\n\n")
            total_non_english_lines = 0
            files_with_non_english = 0
            for result in results:
                if result.non_english_lines:
                    files_with_non_english += 1
                    total_non_english_lines += len(result.non_english_lines)
            f.write(f"Files with non-English content: {files_with_non_english}\n")
            f.write(f"Total non-English lines found: {total_non_english_lines}\n")
            f.write("=" * 40 + "\n\n")
            for result in sorted(results, key=lambda r: len(r.non_english_lines), reverse=True):
                if not result.non_english_lines and not result.error:
                    continue
                f.write(f"\n{'=' * 40}\n")
                f.write(f"File: {result.file_path}\n")
                f.write(f"Total lines: {result.total_lines}\n")
                f.write(f"Non-English lines: {len(result.non_english_lines)}\n")
                if result.error:
                    f.write(f"Error: {result.error}\n")
                    continue
                if result.non_english_lines:
                    f.write("-" * 40 + "\n")
                    for line_info in result.non_english_lines:
                        lang = line_info["detected_lang"]
                        confidence = line_info["confidence"]
                        f.write(
                            f"  Line {line_info['line_number']:>6} | "
                            f"Language: {lang:>6} | "
                            f"Confidence: {confidence:.2%}\n"
                        )
                        f.write(f"  Content: {line_info['text'][:150]}\n")
                        f.write("\n")
            f.write("\n" + "=" * 40 + "\n")
            f.write("End of report\n")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect non-English content in text files recursively",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s /path/to/project --confidence 0.9
  %(prog)s . --extensions .txt .md .py
  %(prog)s . --output custom_report.txt
        """,
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--confidence",
        "-c",
        type=float,
        default=0.85,
        help="Minimum confidence threshold (default: 0.85)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="noneng.txt",
        help="Output file path (default: noneng.txt)",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=10,
        help="Minimum line length to check (default: 10)",
    )
    parser.add_argument("--extensions", nargs="+", help="Additional file extensions to scan")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed progress for each file",
    )
    args = parser.parse_args()
    config = ScanConfig(confidence_threshold=args.confidence, min_line_length=args.min_length)
    if args.extensions:
        config.text_extensions.update(args.extensions)
    start_time = time.time()
    detector = NonEnglishDetector(config)
    try:
        results = detector.scan_directory(Path(args.directory))
        output_path = Path(args.output)
        detector.save_results(results, output_path)
        elapsed = time.time() - start_time
        files_with_issues = sum(1 for r in results if r.non_english_lines)
        total_non_eng = sum(len(r.non_english_lines) for r in results)
        print("\n" + "=" * 40)
        print(f"Scan completed in {elapsed:.1f} seconds")
        print(f"Files scanned: {len(results)}")
        print(f"Files with non-English content: {files_with_issues}")
        print(f"Total non-English lines: {total_non_eng}")
        print(f"Results saved to: {output_path.absolute()}")
        print("-" * 40)
        sys.exit(0 if files_with_issues == 0 else 1)
    except KeyboardInterrupt:
        print("\nScan interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e!s}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
