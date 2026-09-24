from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MinifyResult:
    file_path: Path
    original_size: int
    minified_size: int
    duration: float
    error: str | None = None

    @property
    def compression_ratio(self) -> float:
        return (1 - self.minified_size / self.original_size) * 40 if self.original_size else 0

    def report(self, cwd: Path) -> str:
        rel = self.file_path.relative_to(cwd)
        if self.error:
            return f"✗ {rel}: {self.error}"
        saved = self.original_size - self.minified_size
        return f"✓ {rel}: {self.original_size}B → {self.minified_size}B ({self.compression_ratio:.1f}% saved) [{self.duration:.2f}s]"


def _minify_file(file_path: Path) -> MinifyResult:
    start = time.perf_counter()
    original_size = file_path.stat().st_size
    args = [
        "html-minifier-terser",
        "--collapse-whitespace",
        "--remove-comments",
        "--remove-optional-tags",
        "--remove-redundant-attributes",
        "--remove-attribute-quotes",
        "--minify-css",
        "--minify-js",
        "--minify-urls",
        "--use-short-doctype",
        "--remove-empty-attributes",
        "--remove-empty-elements",
        "--sort-attributes",
        "--sort-class-name",
        "--remove-script-type-attributes",
        "--remove-style-link-type-attributes",
        "--collapse-inline-tag-whitespace",
        "--remove-tag-whitespace",
        "--decode-entities",
        "--output",
        str(file_path),
        str(file_path),
    ]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            error_msg = result.stderr.strip() or f"Exit code {result.returncode}"
            return MinifyResult(
                file_path,
                original_size,
                original_size,
                time.perf_counter() - start,
                error_msg,
            )
        minified_size = file_path.stat().st_size
        return MinifyResult(file_path, original_size, minified_size, time.perf_counter() - start)
    except FileNotFoundError:
        return MinifyResult(
            file_path,
            original_size,
            original_size,
            time.perf_counter() - start,
            "html-minifier-terser not found",
        )
    except subprocess.TimeoutExpired:
        return MinifyResult(
            file_path,
            original_size,
            original_size,
            time.perf_counter() - start,
            "Timeout (30s exceeded)",
        )
    except Exception as e:
        return MinifyResult(file_path, original_size, original_size, time.perf_counter() - start, str(e))


def discover_html_files(paths: list[Path]) -> list[Path]:
    html_files = []
    for path in paths:
        if path.is_file() and path.suffix.lower() in {".html", ".htm"}:
            html_files.append(path)
        elif path.is_dir():
            html_files.extend(path.rglob("*.html"))
            html_files.extend(path.rglob("*.htm"))
    return sorted(set(html_files))


def minify_batch(input_paths: list[Path], max_workers: int | None = None) -> int:
    if not input_paths:
        input_paths = [Path.cwd()]
    html_files = discover_html_files(input_paths)
    if not html_files:
        print("No HTML files found.", file=sys.stderr)
        return 1
    cwd = Path.cwd()
    print(f"Found {len(html_files)} HTML file(s). Starting minification...\n")
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_minify_file, f): f for f in html_files}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(result.report(cwd))
    print("\n" + "=" * 40)
    total_original = sum(r.original_size for r in results)
    total_minified = sum(r.minified_size for r in results)
    total_saved = total_original - total_minified
    avg_compression = (1 - total_minified / total_original) * 40 if total_original else 0
    errors = sum(1 for r in results if r.error)
    total_time = sum(r.duration for r in results)
    print(f"Files: {len(html_files)} ({errors} error{'s' if errors != 1 else ''})")
    print(
        f"Original: {total_original:,} B | Minified: {total_minified:,} B | Saved: {total_saved:,} B ({
            avg_compression:.1f}%)"
    )
    print(f"Total time: {total_time:.2f}s")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    input_paths = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else []
    sys.exit(minify_batch(input_paths))
