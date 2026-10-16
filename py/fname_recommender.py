from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileStats:
    path: Path
    current_name: str
    suggestion: str | None
    has_meaning: bool
    error: str | None = None
    renamed: bool = False
    new_path: Path | None = None


class FileAnalyzer:
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.tree = None
        self.content = ""
        try:
            self.content = filepath.read_text(encoding="utf-8", errors="ignore")
            self.tree = ast.parse(self.content)
        except SyntaxError:
            pass
        except Exception as e:
            raise RuntimeError(f"Failed to read {filepath}: {e}")

    def get_module_docstring(self) -> str | None:
        if not self.tree:
            return None
        return ast.get_docstring(self.tree)

    def get_argparse_epilog(self) -> str | None:
        pattern = r'epilog\s*=\s*[\'"]([^\'"]+)[\'"]'
        match = re.search(pattern, self.content, re.IGNORECASE)
        return match.group(1) if match else None

    def get_main_docstring(self) -> str | None:
        if not self.tree:
            return None
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                return ast.get_docstring(node)
        return None

    def extract_purpose(self) -> str | None:
        return self.get_module_docstring() or self.get_argparse_epilog() or self.get_main_docstring()

    def is_meaningful_name(self) -> bool:
        name = self.filepath.stem
        if len(name) < 3 or name in {"main", "run", "test", "script", "app"}:
            return False
        return not re.match(r"^[a-z0-9]{1,2}$", name)

    def suggest_name(self) -> str | None:
        purpose = self.extract_purpose()
        if not purpose:
            return None
        words = re.findall(r"\b[a-z][a-z0-9]*\b", purpose.lower())
        if not words:
            return None
        stop_words = {
            "this",
            "that",
            "from",
            "with",
            "for",
            "the",
            "and",
            "or",
            "are",
            "is",
        }
        keywords = [w for w in words if len(w) > 3 and w not in stop_words]
        if keywords:
            return "_".join(keywords[:3])
        return "_".join(words[:2]) if len(words) >= 2 else None


def collect_py_files(paths: list[Path]) -> Generator[Path, None, None]:
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            yield from path.rglob("*.py")


def analyze_file(filepath: Path) -> FileStats:
    stats = FileStats(path=filepath, current_name=filepath.stem, suggestion=None, has_meaning=False)
    try:
        analyzer = FileAnalyzer(filepath)
        stats.has_meaning = analyzer.is_meaningful_name()
        if not stats.has_meaning:
            stats.suggestion = analyzer.suggest_name()
    except Exception as e:
        stats.error = str(e)
    return stats


def rename_file(filepath: Path, new_name: str) -> tuple[bool, str | None]:
    try:
        new_path = filepath.parent / f"{new_name}.py"
        if new_path == filepath:
            return False, "New name is identical to current"
        if new_path.exists():
            return False, f"Target already exists: {new_path.name}"
        filepath.rename(new_path)
        return True, None
    except Exception as e:
        return False, str(e)


def process_files(paths: list[Path], apply: bool = False, max_workers: int = 4) -> list[FileStats]:
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for filepath in collect_py_files(paths):
            future = executor.submit(analyze_file, filepath)
            futures[future] = filepath
        for future in as_completed(futures):
            stats = future.result()
            if not stats.has_meaning and stats.suggestion and apply:
                renamed, error = rename_file(stats.path, stats.suggestion)
                if renamed:
                    stats.renamed = True
                    stats.new_path = stats.path.parent / f"{stats.suggestion}.py"
                else:
                    stats.error = f"Rename failed: {error}"
            results.append(stats)
    return sorted(results, key=lambda s: s.path)


def report_stats(stats_list: list[FileStats], cwd: Path, apply: bool) -> None:
    meaningful = sum(1 for s in stats_list if s.has_meaning)
    unnamed = sum(1 for s in stats_list if not s.has_meaning)
    renamed = sum(1 for s in stats_list if s.renamed)
    errors = sum(1 for s in stats_list if s.error)
    mode = "APPLY" if apply else "DRY RUN"
    print(f"\n{'=' * 78}")
    print(f"  Mode: {mode}")
    print(f"  Total files: {len(stats_list)} | Meaningful: {meaningful} | Unnamed: {unnamed}")
    print(f"  Errors: {errors} | Renamed: {renamed}")
    print(f"{'=' * 78}\n")
    if unnamed > 0:
        print("UNNAMED FILES:\n")
        for stats in stats_list:
            if not stats.has_meaning:
                rel_path = stats.path.relative_to(cwd)
                print(f"  📄 {rel_path}")
                print(f"     Current: {stats.current_name}")
                if stats.suggestion:
                    print(f"     Suggest: {stats.suggestion}")
                else:
                    print("     Suggest: (no suggestion available)")
                if stats.error:
                    print(f"     Error:   {stats.error}")
                elif stats.renamed:
                    print(f"     ✓ Renamed to: {stats.suggestion}")
                print()
    if errors > 0:
        print("\nFILES WITH ERRORS:\n")
        for stats in stats_list:
            if stats.error:
                rel_path = stats.path.relative_to(cwd)
                print(f"  ❌ {rel_path}")
                print(f"     {stats.error}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Python files and suggest meaningful filenames",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python script.py
  python script.py . /path/to/project
  python script.py -a
  python script.py file1.py file2.py -a
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[Path(".")],
        help="Files or directories to analyze (default: current directory)",
    )
    parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply suggestions and rename files in place",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    args = parser.parse_args()
    try:
        cwd = Path.cwd()
        results = process_files(args.paths, apply=args.apply, max_workers=args.workers)
        if results:
            report_stats(results, cwd, args.apply)
        else:
            print("No Python files found.")
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
