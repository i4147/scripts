import subprocess
import sys
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from loguru import logger
WORKER_COUNT = 8
MINIFIER_TIMEOUT_SECONDS = 30
HTML_SUFFIXES = frozenset({".html", ".htm"})
MINIFIER_FLAGS = (
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
)
@dataclass
class MinifyResult:
    error = None
    @property
    def compression_ratio(self):
        return (
            (1 - self.minified_size / self.original_size) * 40
            if self.original_size
            else 0.0
        )
    def report(self, cwd):
        rel = self.path.relative_to(cwd)
        if self.error:
            return f"✗ {rel}: {self.error}"
        return (
            f"✓ {rel}: {self.original_size}B → {self.minified_size}B "
            f"({self.compression_ratio:.1f}% saved) [{self.duration:.2f}s]"
        )
def _minify_file(path):
    start = time.perf_counter()
    original_size = path.stat().st_size
    args = [
        "html-minifier-terser",
        *MINIFIER_FLAGS,
        "--output",
        str(path),
        str(path),
    ]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=MINIFIER_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() or f"Exit code {result.returncode}"
            return MinifyResult(
                path,
                original_size,
                original_size,
                time.perf_counter() - start,
                error_msg,
            )
        minified_size = path.stat().st_size
        return MinifyResult(
            path, original_size, minified_size, time.perf_counter() - start
        )
    except FileNotFoundError:
        return MinifyResult(
            path,
            original_size,
            original_size,
            time.perf_counter() - start,
            "html-minifier-terser not found",
        )
    except subprocess.TimeoutExpired:
        return MinifyResult(
            path,
            original_size,
            original_size,
            time.perf_counter() - start,
            f"Timeout ({MINIFIER_TIMEOUT_SECONDS}s exceeded)",
        )
    except Exception as e:  
        return MinifyResult(
            path, original_size, original_size, time.perf_counter() - start, str(e)
        )
def discover_html_files(paths):
    html_files = []
    for path in paths:
        if path.is_file() and path.suffix.lower() in HTML_SUFFIXES:
            html_files.append(path)
        elif path.is_dir():
            html_files.extend(path.rglob("*.html"))
            html_files.extend(path.rglob("*.htm"))
    return sorted(set(html_files))
def minify_batch(input_paths):
    if not input_paths:
        input_paths = [Path.cwd()]
    html_files = discover_html_files(input_paths)
    if not html_files:
        logger.error("No HTML files found.")
        return 1
    cwd = Path.cwd()
    print(f"Found {len(html_files)} HTML file(s). Starting minification...")
    results = []
    with Pool(processes=WORKER_COUNT) as pool:
        async_results = [pool.apply_async(_minify_file, (f,)) for f in html_files]
        for async_result in async_results:
            result = async_result.get()
            results.append(result)
            print(result.report(cwd))
    total_original = sum(r.original_size for r in results)
    total_minified = sum(r.minified_size for r in results)
    total_saved = total_original - total_minified
    avg_compression = (
        (1 - total_minified / total_original) * 40 if total_original else 0.0
    )
    errors = sum(1 for r in results if r.error)
    total_time = sum(r.duration for r in results)
    print("=" * 40)
    print(f"Files: {len(html_files)} ({errors} error{'s' if errors != 1 else ''})")
    print(
        f"Original: {total_original:,} B | Minified: {total_minified:,} B | "
        f"Saved: {total_saved:,} B ({avg_compression:.1f}%)"
    )
    print(f"Total time: {total_time:.2f}s")
    return 0 if errors == 0 else 1
if __name__ == "__main__":
    cli_paths = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else []
    sys.exit(minify_batch(cli_paths))
