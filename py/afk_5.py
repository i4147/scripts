import re
import sys
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class FileResult:
    path: str
    removed_imports: List[str]
    modified: bool
    error: Optional[str] = None


class ImportCleaner:
    ALWAYS_KEEP = {
        ("__future__", "annotations"),
        ("__future__", "print_function"),
        ("__future__", "unicode_literals"),
        ("__future__", "absolute_import"),
        ("__future__", "division"),
        ("__future__", "generators"),
    }

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def find_python_files(self, paths: List[str], recursive: bool = True) -> List[Path]:
        python_files = []
        for path_str in paths:
            path = Path(path_str)
            if path.is_file():
                if path.suffix == ".py":
                    python_files.append(path)
                elif self.verbose:
                    print(f"Skipping non-Python file: {path}")
            elif path.is_dir():
                if recursive:
                    python_files.extend(path.rglob("*.py"))
                else:
                    python_files.extend(path.glob("*.py"))
            else:
                print(f"Path does not exist: {path}", file=sys.stderr)
        return python_files

    def remove_comments_and_strings(self, source: str) -> str:

        def remove_triple_quotes(text, quote_char):
            pattern = re.compile(
                f"{quote_char}{quote_char}{quote_char}.*?{quote_char}{quote_char}{quote_char}", re.DOTALL
            )
            return pattern.sub(" ", text)

        source = remove_triple_quotes(source, '"')
        source = remove_triple_quotes(source, "'")

        source = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', " ", source)
        source = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", " ", source)

        lines = []
        for line in source.split("\n"):
            hash_pos = line.find("#")
            if hash_pos >= 0:
                line = line[:hash_pos]
            lines.append(line)
        source = "\n".join(lines)

        return source

    def extract_imports(self, source_lines: List[str]) -> Dict[int, Dict]:
        imports = {}

        import_pattern = re.compile(r"^\s*import\s+(.+?)(?:\s*#.*)?$")
        from_import_pattern = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(.+?)(?:\s*#.*)?$")

        for i, line in enumerate(source_lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            m = import_pattern.match(line)
            if m:
                imports_line = m.group(1)
                names = set()

                for part in imports_line.split(","):
                    part = part.strip()
                    if " as " in part:
                        original, alias = part.split(" as ")
                        names.add(alias.strip())
                    else:
                        base_name = part.split(".")[0]
                        names.add(base_name)
                if names:
                    imports[i] = {"type": "import", "names": names, "line": line.rstrip("\n"), "module": None}
                continue

            m = from_import_pattern.match(line)
            if m:
                module = m.group(1)
                imports_part = m.group(2)
                names = set()
                for part in imports_part.split(","):
                    part = part.strip()
                    if part == "*":
                        names.add("*")
                    elif " as " in part:
                        original, alias = part.split(" as ")
                        names.add(alias.strip())
                    else:
                        names.add(part.strip())
                if names and "*" not in names:
                    imports[i] = {"type": "from", "names": names, "line": line.rstrip("\n"), "module": module}

        return imports

    def get_all_used_names(self, source_clean: str) -> Set[str]:

        words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", source_clean)
        return set(words)

    def import_is_used(self, import_info: Dict, used_names: Set[str], source_lines: List[str]) -> bool:

        if import_info["type"] == "from" and import_info.get("module") == "__future__":
            return True

        names = import_info["names"]

        if import_info["type"] == "from":
            for name in names:
                if name in used_names:
                    return True

            return False

        for name in names:
            if name in used_names:
                return True

        return False

    def clean_file(self, file_path: Path, in_place: bool = False) -> FileResult:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                original_lines = f.readlines()

            if not any(l.strip() for l in original_lines):
                return FileResult(str(file_path), [], False)

            source = "".join(original_lines)

            clean_source = self.remove_comments_and_strings(source)
            used_names = self.get_all_used_names(clean_source)

            imports = self.extract_imports(original_lines)

            lines_to_remove = set()
            removed_list = []

            for line_num, imp_info in imports.items():
                if not self.import_is_used(imp_info, used_names, original_lines):
                    lines_to_remove.add(line_num)
                    removed_list.append(imp_info["line"].strip())

            if not removed_list:
                if self.verbose:
                    print(f"✓ No unused imports: {file_path}")
                return FileResult(str(file_path), [], False)

            cleaned_lines = [line for i, line in enumerate(original_lines, 1) if i not in lines_to_remove]
            cleaned_content = "".join(cleaned_lines)

            if in_place:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(cleaned_content)
                if self.verbose:
                    print(f"✓ Updated: {file_path}")
            else:
                output_path = file_path.parent / f"{file_path.stem}_cleaned{file_path.suffix}"
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(cleaned_content)
                if self.verbose:
                    print(f"✓ Created: {output_path}")

            return FileResult(str(file_path), removed_list, True)

        except Exception as e:
            error_msg = f"Error processing {file_path}: {str(e)}"
            if self.verbose:
                print(f"✗ {error_msg}", file=sys.stderr)
            return FileResult(str(file_path), [], False, error_msg)

    def process_file_wrapper(self, args: Tuple[str, bool]) -> FileResult:
        return self.clean_file(Path(args[0]), args[1])


def print_summary(results: List[FileResult], verbose: bool = False):
    total = len(results)
    modified = [r for r in results if r.modified]
    errors = [r for r in results if r.error]

    print("\n" + "=" * 70)
    print("IMPORT CLEANUP SUMMARY")
    print("=" * 70)
    print(f"Total files processed: {total}")
    print(f"Files modified: {len(modified)}")
    print(f"Errors: {len(errors)}")

    if modified:
        total_removed = sum(len(r.removed_imports) for r in modified)
        print(f"Total unused imports removed: {total_removed}")

        print("\n" + "-" * 70)
        print("MODIFIED FILES:")
        print("-" * 70)

        for result in modified:
            print(f"\n📄 {result.path}")
            print(f"   Removed {len(result.removed_imports)} import(s):")
            for imp in result.removed_imports[:15]:
                print(f"     - {imp}")
            if len(result.removed_imports) > 15:
                print(f"     ... and {len(result.removed_imports) - 15} more")

    if errors and verbose:
        print("\n" + "-" * 70)
        print("ERRORS:")
        print("-" * 70)
        for result in errors:
            print(f"   ❌ {result.error}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Remove unused imports from Python files (accurate text scanning)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s script.py                    # Clean single file
  %(prog)s src/                         # Clean directory (recursive)
  %(prog)s src/ --no-recursive          # Clean directory (non-recursive)
  %(prog)s . -i -v                      # Clean current directory in place with verbose
  %(prog)s file1.py file2.py --no-mp    # Process multiple files sequentially
  %(prog)s src/ tests/ -i               # Clean multiple directories in place

Note: __future__ imports are always preserved. Imports used inside conditional blocks or
      via module prefixes (e.g., 'import lz4.frame' used as 'lz4.frame.compress()') are detected.
        """,
    )

    parser.add_argument("paths", nargs="+", help="Files or directories to process")
    parser.add_argument(
        "--in-place", "-i", action="store_true", help="Modify files in place (creates _cleaned copies by default)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument(
        "--recursive", "-r", action="store_true", default=True, help="Process directories recursively (default: True)"
    )
    parser.add_argument("--no-recursive", action="store_true", help="Do not process directories recursively")
    parser.add_argument("--no-mp", action="store_true", help="Disable multiprocessing")

    args = parser.parse_args()

    recursive = args.recursive and not args.no_recursive

    cleaner = ImportCleaner(verbose=args.verbose)
    python_files = cleaner.find_python_files(args.paths, recursive)

    if not python_files:
        print("No Python files found to process.")
        return

    if args.verbose:
        print(f"Found {len(python_files)} Python file(s) to process")
        if args.no_mp:
            print("Processing sequentially...")
        else:
            print(f"Processing with {cpu_count()} CPU cores...")

    if args.no_mp or len(python_files) < 2:
        results = []
        for file_path in python_files:
            results.append(cleaner.clean_file(file_path, args.in_place))
    else:
        with Pool(processes=cpu_count()) as pool:
            tasks = [(str(fp), args.in_place) for fp in python_files]
            results = pool.map(cleaner.process_file_wrapper, tasks)

    print_summary(results, args.verbose)


if __name__ == "__main__":
    main()
