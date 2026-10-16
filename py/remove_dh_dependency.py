from __future__ import annotations

import argparse
import ast
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

DH_SOURCE_PATH = Path.home() / "projects" / "py" / "dh" / "src" / "dh"


@dataclass
class ProcessResult:
    file_path: Path
    modified: bool
    new_content: str | None
    error: str | None


class DHModuleAnalyzer:
    def __init__(self, dh_path: Path):
        self.dh_path = dh_path
        self.definitions: dict[str, str] = {}
        self.module_mapping: dict[str, set[str]] = {}
        self._load_dh_definitions()

    def _load_dh_definitions(self):
        if not self.dh_path.exists():
            raise FileNotFoundError(f"DH module path not found: {self.dh_path}")
        py_files = sorted(self.dh_path.glob("*.py"))
        for py_file in py_files:
            if py_file.name == "__init__.py":
                continue
            module_name = py_file.stem
            self.module_mapping[module_name] = set()
            try:
                with open(py_file, encoding="utf-8") as f:
                    content = f.read()
                tree = ast.parse(content)
                lines = content.split("\n")
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        func_name = node.name
                        start_line = node.lineno - 1
                        end_line = node.end_lineno
                        func_source = "\n".join(lines[start_line:end_line])
                        self.definitions[func_name] = func_source
                        self.module_mapping[module_name].add(func_name)
            except Exception as e:
                print(f"⚠ Warning: Could not parse {py_file}: {e}", file=sys.stderr)

    def get_all_definitions(self) -> dict[str, str]:
        return self.definitions.copy()


class ImportRemover(ast.NodeTransformer):
    def __init__(self, definitions: dict[str, str]):
        self.definitions = definitions
        self.inlined_code: list[str] = []
        self.has_dh_imports = False


class PythonFileProcessor:
    def __init__(self, definitions: dict[str, str]):
        self.definitions = definitions

    def process(self, file_path: Path) -> ProcessResult:
        try:
            with open(file_path, encoding="utf-8") as f:
                original_content = f.read()
            tree = ast.parse(original_content)
            transformer = ImportRemover(self.definitions)
            transformer.visit(tree)
            if not transformer.has_dh_imports:
                return ProcessResult(file_path=file_path, modified=False, new_content=None, error=None)
            new_content = self._build_new_content(original_content, transformer.inlined_code)
            return ProcessResult(file_path=file_path, modified=True, new_content=new_content, error=None)
        except SyntaxError as e:
            return ProcessResult(
                file_path=file_path,
                modified=False,
                new_content=None,
                error=f"Syntax error: {e}",
            )
        except Exception as e:
            return ProcessResult(
                file_path=file_path,
                modified=False,
                new_content=None,
                error=f"{type(e).__name__}: {e}",
            )

    def _build_new_content(self, original_content: str, inlined_code: list[str]) -> str:
        lines = original_content.split("\n")
        import_end_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(("import ", "from ")):
                import_end_idx = i + 1
            else:
                break
        filtered_lines = [line for line in lines if not ("from dh import" in line or "import dh" in line)]
        new_lines = filtered_lines[:import_end_idx]
        if inlined_code:
            new_lines.append("\n# ===== Inlined from dh module =====\n")
            new_lines.extend(inlined_code)
            new_lines.append("\n# ===== End of inlined code =====\n")
        new_lines.extend(filtered_lines[import_end_idx:])
        return "\n".join(new_lines)


class ProjectCleaner:
    def __init__(self, dh_path: Path = DH_SOURCE_PATH, max_workers: int | None = None):
        self.dh_path = dh_path.resolve()
        self.max_workers = max_workers
        self.analyzer = DHModuleAnalyzer(self.dh_path)
        self.processor = PythonFileProcessor(self.analyzer.get_all_definitions())
        self.results: list[ProcessResult] = []

    def find_python_files(self, paths: list[Path]) -> list[Path]:
        py_files = set()
        for path in paths:
            path = path.resolve()
            if not path.exists():
                print(f"⚠ Warning: Path does not exist: {path}", file=sys.stderr)
                continue
            if path.is_file():
                if path.suffix == ".py":
                    py_files.add(path)
                else:
                    print(f"⚠ Warning: Not a Python file: {path}", file=sys.stderr)
            elif path.is_dir():
                for py_file in path.rglob("*.py"):
                    if not any(part.startswith(".") for part in py_file.parts):
                        py_files.add(py_file)
        return sorted(py_files)

    def process_parallel(self, py_files: list[Path], dry_run: bool = False) -> dict[str, int]:
        if not py_files:
            print("No Python files to process.")
            return {"total": 0, "modified": 0, "errors": 0}
        print(f"Found {len(py_files)} Python file(s)")
        print(f"Loaded {len(self.analyzer.definitions)} definitions from dh module")
        print(f"Using {self.max_workers or 'all available'} worker(s)\n")
        modified_count = 0
        error_count = 0
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.processor.process, py_file): py_file for py_file in py_files}
            for future in as_completed(futures):
                py_file = futures[future]
                try:
                    result = future.result()
                    self.results.append(result)
                    if result.error:
                        print(f"✗ Error in {py_file}: {result.error}")
                        error_count += 1
                    elif result.modified:
                        if not dry_run:
                            with open(py_file, "w", encoding="utf-8") as f:
                                f.write(result.new_content)
                            print(f"✓ Updated: {py_file}")
                        else:
                            print(f"◇ Would update: {py_file}")
                        modified_count += 1
                    else:
                        print(f"- No changes: {py_file}")
                except Exception as e:
                    print(f"✗ Exception processing {py_file}: {e}")
                    error_count += 1
        stats = {
            "total": len(py_files),
            "modified": modified_count,
            "errors": error_count,
        }
        return stats

    def print_summary(self, stats: dict[str, int], dry_run: bool = False):
        print(f"\n{'=' * 40}")
        print("Processing Complete!")
        print(f"{'=' * 40}")
        print(f"Total files processed:  {stats['total']}")
        print(f"Files modified:         {stats['modified']}")
        print(f"Errors:                 {stats['errors']}")
        if dry_run:
            print("\nⓘ Dry run mode - no changes saved")
        modified_files = [r.file_path for r in self.results if r.modified]
        if modified_files and stats["total"] <= 20:
            print("\nModified files:")
            for f in modified_files:
                print(f"  {f}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove dependencies on 'dh' module by inlining function code.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  # Process current directory recursively\n  %(prog)s\n\n  # Process specific files\n  %(prog)s script1.py script2.py\n\n  # Process specific directories\n  %(prog)s src/ tests/\n\n  # Mix files and directories\n  %(prog)s main.py src/ tests/utils.py\n\n  # Dry run to preview changes\n  %(prog)s --dry-run\n\n  # Custom dh module path\n  %(prog)s --dh-path /path/to/dh/src/dh src/\n\n  # Parallel processing with specific workers\n  %(prog)s --workers 4 src/ tests/\n        ",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )
    parser.add_argument(
        "--dh-path",
        type=Path,
        default=DH_SOURCE_PATH,
        help=f"Path to dh module source (default: {DH_SOURCE_PATH})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers (default: CPU count)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.paths:
        paths = args.paths
    else:
        paths = [Path(".")]
    try:
        cleaner = ProjectCleaner(dh_path=args.dh_path, max_workers=args.workers)
        py_files = cleaner.find_python_files(paths)
        if not py_files:
            print("No Python files found to process.")
            sys.exit(0)
        stats = cleaner.process_parallel(py_files, dry_run=args.dry_run)
        cleaner.print_summary(stats, dry_run=args.dry_run)
        sys.exit(1 if stats["errors"] > 0 else 0)
    except FileNotFoundError as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"✗ Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
