import argparse
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class MinifyResult:
    path: Path
    original_size: int
    minified_size: int
    success: bool
    error: Optional[str] = None

    @property
    def savings_bytes(self) -> int:
        return self.original_size - self.minified_size

    @property
    def savings_percent(self) -> float:
        if self.original_size == 0:
            return 0.0
        return (self.savings_bytes / self.original_size) * 100


def check_html_minifier() -> bool:
    try:
        result = subprocess.run(["html-minifier-terser", "--version"], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def find_html_files(paths: list[Path]) -> list[Path]:
    html_files = []
    html_extensions = {".html", ".htm"}
    for path in paths:
        if path.is_file():
            if path.suffix.lower() in html_extensions:
                html_files.append(path)
        elif path.is_dir():
            for ext in html_extensions:
                html_files.extend(path.rglob(f"*{ext}"))
                html_files.extend(path.rglob(f"*{ext.upper()}"))

    seen = set()
    unique_files = []
    for file in html_files:
        if file not in seen:
            seen.add(file)
            unique_files.append(file)
    return unique_files


def minify_single_file(file_path: Path) -> MinifyResult:
    try:
        original_size = file_path.stat().st_size

        temp_path = file_path.with_suffix(file_path.suffix + ".tmp")

        cmd = [
            "html-minifier-terser",
            str(file_path),
            "-o",
            str(temp_path),
            "--collapse-whitespace",
            "--remove-comments",
            "--remove-redundant-attributes",
            "--remove-script-type-attributes",
            "--remove-style-link-type-attributes",
            "--minify-css",
            "true",
            "--minify-js",
            "true",
            "--case-sensitive",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return MinifyResult(
                path=file_path,
                original_size=original_size,
                minified_size=original_size,
                success=False,
                error=result.stderr or "Unknown error",
            )

        if not temp_path.exists():
            return MinifyResult(
                path=file_path,
                original_size=original_size,
                minified_size=original_size,
                success=False,
                error="Minified output not created",
            )

        minified_size = temp_path.stat().st_size

        temp_path.replace(file_path)
        return MinifyResult(path=file_path, original_size=original_size, minified_size=minified_size, success=True)
    except subprocess.TimeoutExpired:
        return MinifyResult(
            path=file_path,
            original_size=file_path.stat().st_size if file_path.exists() else 0,
            minified_size=file_path.stat().st_size if file_path.exists() else 0,
            success=False,
            error="Timeout exceeded",
        )
    except Exception as e:
        return MinifyResult(
            path=file_path,
            original_size=file_path.stat().st_size if file_path.exists() else 0,
            minified_size=file_path.stat().st_size if file_path.exists() else 0,
            success=False,
            error=str(e),
        )
    finally:
        if "temp_path" in locals() and temp_path.exists():
            temp_path.unlink()


def format_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.0f} {unit}" if unit == "B" else f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def print_results(results: list[MinifyResult], base_path: Path):
    print("\n" + "=" * 42)
    print(f"{'File':<40} {'Savings':<10} {'Percent':<10} {'Status'}")
    print("=" * 42)
    total_original = 0
    total_minified = 0
    success_count = 0
    fail_count = 0
    for result in sorted(results, key=lambda r: r.path):
        try:
            rel_path = result.path.relative_to(base_path)
        except ValueError:
            rel_path = result.path
        savings = result.savings_bytes
        percent = result.savings_percent
        if result.success:
            status = "✓"
            success_count += 1
        else:
            status = f"✗ ({result.error})"
            fail_count += 1
        total_original += result.original_size
        total_minified += result.minified_size
        print(f"{str(rel_path):<40} -{format_size(savings):>7}  {percent:>6.1f}%  {status}")
    print("=" * 42)
    if success_count > 0:
        total_savings = total_original - total_minified
        total_percent = (total_savings / total_original * 100) if total_original > 0 else 0
        print(f"Total: {success_count} files minified, {fail_count} failed")
        print(f"Total savings: {format_size(total_savings)} ({total_percent:.1f}%)")
        print(f"Original size: {format_size(total_original)}")
        print(f"Minified size: {format_size(total_minified)}")


def main():
    parser = argparse.ArgumentParser(
        description="Minify HTML files using html-minifier-terser with parallel processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Minify all HTML files in current directory
  %(prog)s index.html about.html     # Minify specific files
  %(prog)s src/ templates/           # Minify files in specific directories
  %(prog)s -w 8 src/                 # Use 8 worker processes
        """,
    )
    parser.add_argument("paths", nargs="*", help="Files or directories to process (default: current directory)")
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=os.cpu_count(),
        help=f"Number of parallel workers (default: {os.cpu_count()})",
    )
    parser.add_argument("--no-parallel", action="store_true", help="Disable parallel processing")
    args = parser.parse_args()

    if not check_html_minifier():
        print("Error: html-minifier-terser is not installed or not in PATH")
        print("Install it with: npm install -g html-minifier-terser")
        sys.exit(1)

    if args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        paths = [Path.cwd()]

    for path in paths:
        if not path.exists():
            print(f"Error: Path '{path}' does not exist")
            sys.exit(1)

    print("Finding HTML files...")
    html_files = find_html_files(paths)
    if not html_files:
        print("No HTML files found")
        return
    print(f"Found {len(html_files)} HTML file(s)")
    print(f"Using {args.workers} worker(s) for parallel processing\n")

    base_path = Path.cwd()

    results = []
    if args.no_parallel or len(html_files) == 1:
        for file in html_files:
            result = minify_single_file(file)
            results.append(result)
            if result.success:
                savings = result.savings_bytes
                percent = result.savings_percent
                rel_path = result.path.relative_to(base_path) if base_path in result.path.parents else result.path
                print(f"  ✓ {rel_path} | -{format_size(savings)} | {percent:.1f}%")
            else:
                print(f"  ✗ {result.path} | Error: {result.error}")
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            future_to_file = {executor.submit(minify_single_file, file): file for file in html_files}
            for future in as_completed(future_to_file):
                result = future.result()
                results.append(result)
                file = future_to_file[future]
                if result.success:
                    savings = result.savings_bytes
                    percent = result.savings_percent
                    try:
                        rel_path = file.relative_to(base_path)
                    except ValueError:
                        rel_path = file
                    print(f"  ✓ {rel_path} | -{format_size(savings)} | {percent:.1f}%")
                else:
                    print(f"  ✗ {file} | Error: {result.error}")

    print_results(results, base_path)


if __name__ == "__main__":
    main()
