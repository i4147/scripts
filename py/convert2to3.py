from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from lib2to3.refactor import RefactoringTool, get_fixers_from_package
from pathlib import Path
from typing import list, tuple

logging.getLogger("lib2to3").setLevel(logging.WARNING)


class CustomRefactoringTool(RefactoringTool):
    def __init__(self, fixers, explicit=None, append=None) -> None:
        self.output_lines = []
        self.errors = []
        super().__init__(fixers, explicit, append)

    def log_error(self, msg, *args, **kwargs) -> None:
        self.errors.append(msg % args)

    def write(self, msg, *args, **kwargs) -> None:
        if args:
            msg = msg % args
        self.output_lines.append(msg)


def get_all_fixers() -> list[str]:
    try:
        fixers = get_fixers_from_package("lib2to3.fixes")
        return fixers
    except ImportError as e:
        print(f"Error loading fixers: {e}", file=sys.stderr)
        return [
            "lib2to3.fixes.fix_apply",
            "lib2to3.fixes.fix_asserts",
            "lib2to3.fixes.fix_basestring",
            "lib2to3.fixes.fix_buffer",
            "lib2to3.fixes.fix_dict",
            "lib2to3.fixes.fix_except",
            "lib2to3.fixes.fix_exec",
            "lib2to3.fixes.fix_execfile",
            "lib2to3.fixes.fix_exitfunc",
            "lib2to3.fixes.fix_filter",
            "lib2to3.fixes.fix_funcattrs",
            "lib2to3.fixes.fix_future",
            "lib2to3.fixes.fix_getcwdu",
            "lib2to3.fixes.fix_has_key",
            "lib2to3.fixes.fix_idioms",
            "lib2to3.fixes.fix_import",
            "lib2to3.fixes.fix_imports",
            "lib2to3.fixes.fix_imports2",
            "lib2to3.fixes.fix_input",
            "lib2to3.fixes.fix_itertools",
            "lib2to3.fixes.fix_itertools_imports",
            "lib2to3.fixes.fix_long",
            "lib2to3.fixes.fix_map",
            "lib2to3.fixes.fix_metaclass",
            "lib2to3.fixes.fix_methodattrs",
            "lib2to3.fixes.fix_ne",
            "lib2to3.fixes.fix_next",
            "lib2to3.fixes.fix_nonzero",
            "lib2to3.fixes.fix_numliterals",
            "lib2to3.fixes.fix_operator",
            "lib2to3.fixes.fix_paren",
            "lib2to3.fixes.fix_print",
            "lib2to3.fixes.fix_raise",
            "lib2to3.fixes.fix_raw_input",
            "lib2to3.fixes.fix_reduce",
            "lib2to3.fixes.fix_reload",
            "lib2to3.fixes.fix_renames",
            "lib2to3.fixes.fix_repr",
            "lib2to3.fixes.fix_set_literal",
            "lib2to3.fixes.fix_standarderror",
            "lib2to3.fixes.fix_sys_exc",
            "lib2to3.fixes.fix_throw",
            "lib2to3.fixes.fix_tuple_params",
            "lib2to3.fixes.fix_types",
            "lib2to3.fixes.fix_unicode",
            "lib2to3.fixes.fix_urllib",
            "lib2to3.fixes.fix_ws_comma",
            "lib2to3.fixes.fix_xrange",
            "lib2to3.fixes.fix_xreadlines",
            "lib2to3.fixes.fix_zip",
        ]


def apply_2to3_fixes(file_path: str) -> tuple[str, bool, str]:
    try:
        with open(file_path, encoding="utf-8") as f:
            original_content = f.read()
        all_fixers = get_all_fixers()
        tool = CustomRefactoringTool(fixers=all_fixers, explicit=all_fixers)
        try:
            refactored = tool.refactor_string(original_content, file_path)
            if refactored and refactored != original_content:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(refactored)
                diff_lines = []
                original_lines = original_content.splitlines()
                refactored_lines = refactored.splitlines()
                changes = 0
                for i, (orig, new) in enumerate(zip(original_lines, refactored_lines, strict=False)):
                    if orig != new:
                        changes += 1
                        diff_lines.append(f"  Line {i + 1}: {orig[:50]} -> {new[:50]}")
                message = f"Changed {changes} line(s)"
                if diff_lines:
                    message += "\n" + "\n".join(diff_lines[:5])
                if len(diff_lines) > 5:
                    message += f"\n  ... and {len(diff_lines) - 5} more changes"
                return file_path, True, message
            else:
                return file_path, True, "No changes needed"
        except SyntaxError as e:
            return file_path, False, f"Syntax error in file: {e}"
        except Exception as e:
            return file_path, False, f"Refactoring error: {e!s}"
    except FileNotFoundError:
        return file_path, False, "File not found"
    except PermissionError:
        return file_path, False, "Permission denied"
    except Exception as e:
        return file_path, False, f"Unexpected error: {e!s}"


def find_python_files(paths: list[str], extensions: list[str] | None = None) -> list[str]:
    if extensions is None:
        extensions = [".py"]
    python_files = []
    for path in paths:
        path_obj = Path(path)
        if not path_obj.exists():
            print(f"Warning: Path '{path}' does not exist", file=sys.stderr)
            continue
        if path_obj.is_file():
            if path_obj.suffix in extensions:
                python_files.append(str(path_obj))
        elif path_obj.is_dir():
            for ext in extensions:
                python_files.extend(str(p) for p in path_obj.rglob(f"*{ext}"))
    return python_files


def process_files_parallel(file_paths: list[str]) -> tuple[list[str], list[str]]:
    successful = []
    failed = []
    print(f"Processing {len(file_paths)} files using {4} workers...")
    print("-" * 40)
    with ProcessPoolExecutor(max_workers=4) as executor:
        future_to_file = {executor.submit(apply_2to3_fixes, file_path): file_path for file_path in file_paths}
        for i, future in enumerate(as_completed(future_to_file), 1):
            file_path = future_to_file[future]
            try:
                result_file_path, success, message = future.result()
                if success:
                    successful.append(result_file_path)
                    status = "✓"
                else:
                    failed.append(result_file_path)
                    status = "✗"
                print(f"[{i}/{len(file_paths)}] {status} {Path(result_file_path).name}")
                if message != "No changes needed":
                    print(f"    {message}")
            except Exception as e:
                failed.append(file_path)
                print(f"[{i}/{len(file_paths)}] ✗ {Path(file_path).name}")
                print(f"    Unexpected error: {e!s}")
    return successful, failed


def dry_run_file(file_path: str) -> tuple[str, str, bool]:
    try:
        with open(file_path, encoding="utf-8") as f:
            original_content = f.read()
        all_fixers = get_all_fixers()
        tool = CustomRefactoringTool(fixers=all_fixers, explicit=all_fixers)
        try:
            refactored = tool.refactor_string(original_content, file_path)
            if refactored and refactored != original_content:
                original_lines = original_content.splitlines()
                refactored_lines = refactored.splitlines()
                diff = []
                for _i, (orig, new) in enumerate(zip(original_lines, refactored_lines, strict=False)):
                    if orig != new:
                        diff.append(f"  - {orig[:80]}")
                        diff.append(f"  + {new[:80]}")
                if len(original_lines) != len(refactored_lines):
                    diff.append(f"  (Line count changed: {len(original_lines)} -> {len(refactored_lines)})")
                return file_path, "\n".join(diff[:20]), True
            else:
                return file_path, "No changes needed", False
        except SyntaxError as e:
            return file_path, f"Syntax error: {e}", False
        except Exception as e:
            return file_path, f"Error: {e!s}", False
    except Exception as e:
        return file_path, f"Error reading file: {e!s}", False


def perform_dry_run(file_paths: list[str]) -> None:
    print(f"\nDRY RUN - Preview of changes using {4} workers:")
    print("-" * 40)
    files_with_changes = 0
    with ProcessPoolExecutor(max_workers=4) as executor:
        future_to_file = {executor.submit(dry_run_file, file_path): file_path for file_path in file_paths}
        for future in as_completed(future_to_file):
            file_path, output, has_changes = future.result()
            if has_changes:
                files_with_changes += 1
                print(f"\n📝 {Path(file_path).name}:")
                print(output)
                if output.count("\n") > 20:
                    print("  ... (truncated, use -v for full output)")
            else:
                print(f"✓ {Path(file_path).name}: {output}")
    print(f"\n{'=' * 40}")
    print(f"Dry run complete: {files_with_changes} of {len(file_paths)} files would be changed")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply all available 2to3 fixes to Python files using lib2to3 and multiprocessing"
    )
    parser.add_argument("paths", nargs="+", help="Files or directories to process")
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them",
    )
    parser.add_argument(
        "-e",
        "--extensions",
        nargs="+",
        default=[".py"],
        help="File extensions to process (default: .py)",
    )
    args = parser.parse_args()
    python_files = find_python_files(args.paths, args.extensions)
    if not python_files:
        print("No Python files found to process.")
        return 1
    python_files = list(dict.fromkeys(python_files))
    print(f"Found {len(python_files)} Python file(s) to process")
    if args.dry_run:
        perform_dry_run(python_files)
        return 0
    successful, failed = process_files_parallel(python_files)
    print("\n" + "=" * 40)
    print("SUMMARY")
    print("-" * 40)
    print(f"Total files processed: {len(python_files)}")
    print(f"✓ Successful: {len(successful)}")
    print(f"✗ Failed: {len(failed)}")
    if failed:
        print("\nFailed files:")
        for f in failed:
            print(f"  - {Path(f).name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
