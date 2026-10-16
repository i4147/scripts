from __future__ import annotations

import ast
import io
import shutil
import sys
import time
import tokenize
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import cpu_count
from pathlib import Path

RE_FUNCTIONS = {
    "compile",
    "search",
    "match",
    "fullmatch",
    "split",
    "findall",
    "finditer",
    "sub",
    "subn",
}
SKIP_TOKEN_TYPES = {
    tokenize.NL,
    tokenize.COMMENT,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.TYPE_COMMENT,
    tokenize.ERRORTOKEN,
}
REGEX_INDICATORS = {
    "\\d",
    "\\w",
    "\\s",
    "\\S",
    "\\W",
    "\\D",
    "\\b",
    "\\B",
    "\\A",
    "\\Z",
    "\\z",
    "[",
    "]",
    "(",
    ")",
    "{",
    "}",
    "|",
    "^",
    "$",
    "+",
    "*",
    "?",
    ".",
    "\\1",
    "\\2",
    "\\3",
    "\\4",
    "\\5",
    "\\6",
    "\\7",
    "\\8",
    "\\9",
    "\\0",
}


@dataclass
class StringModification:
    start: tuple[int, int]
    end: tuple[int, int]
    original: str
    modified: str
    line_offset: int = 0


@dataclass
class ProcessingStats:
    total_files: int = 0
    processed: int = 0
    modified: int = 0
    errors: int = 0
    skipped: int = 0
    start_time: float = field(default_factory=time.time)

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time


class RegexFixer:
    def __init__(
        self,
        create_backup: bool = True,
        dry_run: bool = False,
        verbose: bool = False,
        max_workers: int | None = None,
    ):
        self.create_backup = create_backup
        self.dry_run = dry_run
        self.verbose = verbose
        self.max_workers = max_workers or min(cpu_count(), 8)
        self.stats = ProcessingStats()

    def should_convert_string(self, content: str) -> bool:
        if not content:
            return False
        escape_count = 0
        i = 0
        while i < len(content) - 1:
            if content[i] == "\\":
                if content[i + 1] in "\\abfnrtv\"'01234567xNuU":
                    escape_count += 1
                    if escape_count >= 2:
                        return True
                    for indicator in REGEX_INDICATORS:
                        if content[i : i + len(indicator)] == indicator:
                            return True
                i += 1
            i += 1
        return bool(any(indicator in content for indicator in REGEX_INDICATORS))

    def parse_string_literal(self, token_str: str) -> tuple[str, str, str, bool]:
        prefix_end = 0
        for ch in token_str:
            if ch in ('"', "'"):
                break
            prefix_end += 1
        else:
            return (token_str, "", "", False)
        prefix = token_str[:prefix_end]
        is_raw = "r" in prefix.lower()
        "f" in prefix.lower()
        "b" in prefix.lower()
        quote_char = token_str[prefix_end]
        quote_len = 1
        if len(token_str) >= prefix_end + 3 and token_str[prefix_end : prefix_end + 3] == quote_char * 3:
            quote_len = 3
        opening = quote_char * quote_len
        content_start = prefix_end + quote_len
        content_end = len(token_str) - quote_len
        if content_end <= content_start:
            return (prefix, opening, "", is_raw)
        content = token_str[content_start:content_end]
        return (prefix, opening, content, is_raw)

    def convert_string(self, token_str: str) -> str | None:
        prefix, opening, content, is_raw = self.parse_string_literal(token_str)
        if is_raw:
            return None
        if "b" in prefix.lower():
            return None
        if not self.should_convert_string(content):
            return None
        new_content = content.replace("\\\\", "\\")
        new_prefix = prefix
        if "f" in prefix.lower() and "r" not in prefix.lower():
            new_prefix = "rf" + prefix.replace("f", "").replace("F", "")
        elif "r" not in prefix.lower():
            new_prefix = "r" + prefix
        return f"{new_prefix}{opening}{new_content}{opening}"

    def process_tokens(self, code: str) -> list[StringModification]:
        modifications = []
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
        except tokenize.TokenError:
            return modifications
        relevant = []
        for tok in tokens:
            if tok.type in SKIP_TOKEN_TYPES:
                continue
            if tok.type in (tokenize.NAME, tokenize.OP, tokenize.STRING) or tok.type == tokenize.NUMBER:
                relevant.append(tok)
        i = 0
        while i < len(relevant) - 4:
            if (
                relevant[i].type == tokenize.NAME
                and relevant[i].string == "re"
                and (i + 1 < len(relevant))
                and (relevant[i + 1].type == tokenize.OP)
                and (relevant[i + 1].string == ".")
                and (i + 2 < len(relevant))
                and (relevant[i + 2].type == tokenize.NAME)
                and (relevant[i + 2].string in RE_FUNCTIONS)
                and (i + 3 < len(relevant))
                and (relevant[i + 3].type == tokenize.OP)
                and (relevant[i + 3].string == "(")
                and (i + 4 < len(relevant))
                and (relevant[i + 4].type == tokenize.STRING)
            ):
                str_token = relevant[i + 4]
                new_str = self.convert_string(str_token.string)
                if new_str is not None and new_str != str_token.string:
                    modifications.append(
                        StringModification(
                            start=str_token.start,
                            end=str_token.end,
                            original=str_token.string,
                            modified=new_str,
                        )
                    )
                i += 5
            else:
                i += 1
        return modifications

    def apply_modifications(self, code: str, modifications: list[StringModification]) -> str:
        if not modifications:
            return code
        lines = code.splitlines(keepends=True)
        line_offsets = [0]
        for line in lines:
            line_offsets.append(line_offsets[-1] + len(line))
        sorted_mods = sorted(modifications, key=lambda x: (x.start[0], x.start[1]), reverse=True)
        result_parts = []
        last_end = len(code)
        for mod in sorted_mods:
            start_abs = line_offsets[mod.start[0] - 1] + mod.start[1]
            end_abs = line_offsets[mod.end[0] - 1] + mod.end[1]
            result_parts.append(code[end_abs:last_end])
            result_parts.append(mod.modified)
            last_end = start_abs
        result_parts.append(code[:last_end])
        result_parts.reverse()
        return "".join(result_parts)

    def validate_code(self, code: str) -> bool:
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def process_file(self, filepath: Path) -> tuple[Path, bool, str]:
        try:
            original_code = filepath.read_text(encoding="utf-8")
        except Exception as e:
            return (filepath, False, f"Failed to read: {e}")
        if "re." not in original_code:
            return (filepath, True, "No re calls found")
        modifications = self.process_tokens(original_code)
        if not modifications:
            return (filepath, True, "No changes needed")
        if self.verbose:
            print(f"Found {len(modifications)} modification(s) in {filepath.name}")
            for mod in modifications:
                print(f"  {mod.original} -> {mod.modified}")
        new_code = self.apply_modifications(original_code, modifications)
        if not self.validate_code(new_code):
            return (
                filepath,
                False,
                "Validation failed - syntax error after conversion",
            )
        if self.dry_run:
            return (filepath, True, f"Would modify {len(modifications)} string(s)")
        if self.create_backup:
            backup_path = filepath.with_suffix(filepath.suffix + ".bak")
            try:
                shutil.copy2(filepath, backup_path)
            except Exception as e:
                return (filepath, False, f"Failed to create backup: {e}")
        try:
            filepath.write_text(new_code, encoding="utf-8")
            return (filepath, True, f"✓ Modified {len(modifications)} string(s)")
        except Exception as e:
            return (filepath, False, f"Failed to write: {e}")

    def collect_files(self, paths: list[Path]) -> list[Path]:
        python_files = set()
        exclude_dirs = {
            ".venv",
            "venv",
            "env",
            "__pycache__",
            ".git",
            ".hg",
            ".svn",
            "node_modules",
            "dist",
            "build",
            ".tox",
            ".pytest_cache",
        }
        for path in paths:
            if not path.exists():
                print(f"Warning: Path does not exist: {path}", file=sys.stderr)
                continue
            if path.is_file():
                if path.suffix == ".py":
                    python_files.add(path)
            elif path.is_dir():
                for py_file in path.rglob("*.py"):
                    if any(part in exclude_dirs for part in py_file.parts):
                        continue
                    python_files.add(py_file)
        return sorted(python_files)

    def process_files(self, files: list[Path]) -> list[tuple[Path, bool, str]]:
        if not files:
            return []
        self.stats.total_files = len(files)
        if len(files) == 1 or self.max_workers <= 1:
            results = []
            for i, filepath in enumerate(files, 1):
                if self.verbose and i % 10 == 0:
                    print(f"Progress: {i}/{len(files)}", flush=True)
                result = self.process_file(filepath)
                results.append(result)
                self._update_stats(result)
            return results
        else:
            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(self.process_file, f) for f in files]
                results = []
                for i, future in enumerate(futures, 1):
                    try:
                        result = future.result()
                        results.append(result)
                        self._update_stats(result)
                        if self.verbose and i % 10 == 0:
                            print(f"Progress: {i}/{len(files)}", flush=True)
                    except Exception as e:
                        results.append((files[i - 1], False, f"Error: {e}"))
                        self.stats.errors += 1
                return results

    def _update_stats(self, result: tuple[Path, bool, str]):
        _, success, message = result
        if success:
            self.stats.processed += 1
            if "Modified" in message or "Would modify" in message:
                self.stats.modified += 1
            elif "No changes" in message:
                self.stats.skipped += 1
        else:
            self.stats.errors += 1

    def print_summary(self, results: list[tuple[Path, bool, str]]):
        if not results:
            print("\nNo files processed.")
            return
        print("\n" + "=" * 40)
        modified = []
        unchanged = []
        errors = []
        for filepath, success, message in results:
            if not success:
                errors.append((filepath, message))
            elif "Modified" in message or "Would modify" in message:
                modified.append((filepath, message))
            else:
                unchanged.append((filepath, message))
        if modified:
            print("\n📝 Modified files:")
            for filepath, message in modified:
                rel_path = self._get_relative_path(filepath)
                print(f"  ✓ {rel_path}")
                if self.verbose:
                    print(f"    {message}")
        if errors:
            print("\n❌ Errors:")
            for filepath, message in errors:
                rel_path = self._get_relative_path(filepath)
                print(f"  ✗ {rel_path}: {message}")
        print("\n" + "=" * 40)
        print("\n📊 Summary:")
        print(f"  Total files:     {self.stats.total_files}")
        print(f"  Processed:       {self.stats.processed}")
        print(f"  Modified:        {self.stats.modified}")
        print(f"  Unchanged:       {self.stats.skipped}")
        print(f"  Errors:          {self.stats.errors}")
        print(f"  Time elapsed:    {self.stats.elapsed:.2f}s")
        print(f"  Workers:         {self.max_workers}")
        print(f"  Backup:          {('Enabled' if self.create_backup else 'Disabled')}")
        print(f"  Dry run:         {('Yes' if self.dry_run else 'No')}")

    def _get_relative_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(Path.cwd()))
        except ValueError:
            return str(path)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Fix regex string literals in Python files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n  # Fix all Python files in current directory\n  python fix_regex.py\n\n  # Fix specific files or directories\n  python fix_regex.py src/ tests/test_regex.py\n\n  # Use 4 parallel workers, disable backups\n  python fix_regex.py --workers 4 --no-backup\n\n  # Preview changes without modifying files\n  python fix_regex.py --dry-run --verbose\n        ",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        help="Number of parallel workers (default: min(CPU cores, 8))",
    )
    parser.add_argument("--no-backup", action="store_true", help="Disable backup creation")
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Preview changes without modifying files",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimize output")
    args = parser.parse_args()
    if args.paths:
        paths = [Path(p).resolve() for p in args.paths]
    else:
        paths = [Path.cwd()]
    fixer = RegexFixer(
        create_backup=not args.no_backup,
        dry_run=args.dry_run,
        verbose=args.verbose,
        max_workers=args.workers,
    )
    if not args.quiet:
        print(f"📁 Collecting Python files from {len(paths)} path(s)...")
    files = fixer.collect_files(paths)
    if not files:
        print("No Python files found.")
        return
    if not args.quiet:
        print(f"✅ Found {len(files)} Python files")
        print(f"🔧 Processing with {fixer.max_workers} worker(s)")
        print(f"💾 Backup: {('Enabled' if fixer.create_backup else 'Disabled')}")
        if fixer.dry_run:
            print("🔍 DRY RUN - No files will be modified")
        print()
    results = fixer.process_files(files)
    fixer.print_summary(results)
    if fixer.stats.errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
