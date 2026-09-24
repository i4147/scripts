import re
import sys
from pathlib import Path
from typing import Tuple, Optional
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
import logging
from tqdm import tqdm


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    file_path: Path
    success: bool
    original_lines: int
    final_lines: int
    comments_removed: int
    error: Optional[str] = None


class CommentRemover:
    STRING_PATTERN = r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')"""

    SINGLE_COMMENT_PATTERN = r"//.*?(?=\n|$)"

    MULTI_COMMENT_PATTERN = r"/\*.*?\*/"

    def __init__(self):
        self.string_regex = re.compile(self.STRING_PATTERN)
        self.single_comment_regex = re.compile(self.SINGLE_COMMENT_PATTERN)
        self.multi_comment_regex = re.compile(self.MULTI_COMMENT_PATTERN, re.DOTALL)

    def _protect_strings(self, text: str) -> Tuple[str, dict]:
        protected_strings = {}
        placeholder_counter = [0]

        def replace_string(match):
            placeholder = f"__STRING_PLACEHOLDER_{placeholder_counter[0]}__"
            protected_strings[placeholder] = match.group(0)
            placeholder_counter[0] += 1
            return placeholder

        protected_text = self.string_regex.sub(replace_string, text)
        return protected_text, protected_strings

    def _restore_strings(self, text: str, protected_strings: dict) -> str:
        for placeholder, original in protected_strings.items():
            text = text.replace(placeholder, original)
        return text

    def remove_comments(self, text: str) -> Tuple[str, int]:

        protected_text, protected_strings = self._protect_strings(text)

        single_count = len(self.single_comment_regex.findall(protected_text))
        multi_count = len(self.multi_comment_regex.findall(protected_text))
        total_comments = single_count + multi_count

        protected_text = self.single_comment_regex.sub("", protected_text)

        protected_text = self.multi_comment_regex.sub("", protected_text)

        lines = protected_text.split("\n")
        cleaned_lines = []
        for line in lines:
            stripped = line.rstrip()
            cleaned_lines.append(stripped)

        final_lines = []
        prev_empty = False
        for line in cleaned_lines:
            if not line.strip():
                if not prev_empty:
                    final_lines.append(line)
                prev_empty = True
            else:
                final_lines.append(line)
                prev_empty = False

        protected_text = "\n".join(final_lines)

        cleaned_text = self._restore_strings(protected_text, protected_strings)

        return cleaned_text, total_comments

    def process_file(self, file_path: Path) -> ProcessResult:
        try:
            original_content = file_path.read_text(encoding="utf-8")
            original_lines = len(original_content.split("\n"))

            cleaned_content, comments_removed = self.remove_comments(original_content)
            final_lines = len(cleaned_content.split("\n"))

            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            backup_path.write_text(original_content, encoding="utf-8")

            file_path.write_text(cleaned_content, encoding="utf-8")

            return ProcessResult(
                file_path=file_path,
                success=True,
                original_lines=original_lines,
                final_lines=final_lines,
                comments_removed=comments_removed,
            )

        except UnicodeDecodeError as e:
            return ProcessResult(
                file_path=file_path,
                success=False,
                original_lines=0,
                final_lines=0,
                comments_removed=0,
                error=f"Encoding error: {e}",
            )
        except Exception as e:
            return ProcessResult(
                file_path=file_path,
                success=False,
                original_lines=0,
                final_lines=0,
                comments_removed=0,
                error=f"Processing error: {e}",
            )


def find_source_files(root_dir: Path) -> list:
    extensions = {".h", ".hpp", ".c", ".cpp", ".cc", ".cxx", ".hxx"}
    files = []
    for ext in extensions:
        files.extend(root_dir.rglob(f"*{ext}"))
    return sorted(files)


def process_files_parallel(file_paths: list, num_workers: int = None) -> list:
    num_workers = num_workers or cpu_count()
    remover = CommentRemover()

    with Pool(num_workers) as pool:
        results = list(
            tqdm(
                pool.imap_unordered(remover.process_file, file_paths),
                total=len(file_paths),
                desc="Processing files",
                unit="file",
            )
        )

    return results


def print_summary(results: list) -> None:
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    total_comments = sum(r.comments_removed for r in successful)
    total_lines_removed = sum(r.original_lines - r.final_lines for r in successful)

    logger.info("=" * 60)
    logger.info("Processing Summary:")
    logger.info(f"  Files processed: {len(results)}")
    logger.info(f"  Successful: {len(successful)}")
    logger.info(f"  Failed: {len(failed)}")
    logger.info(f"  Total comments removed: {total_comments}")
    logger.info(f"  Total lines removed: {total_lines_removed}")
    logger.info("=" * 60)

    if successful:
        logger.info("Successful files:")
        for result in sorted(successful, key=lambda r: r.file_path):
            logger.info(
                f"  {result.file_path.relative_to(Path.cwd())}: "
                f"{result.comments_removed} comments, "
                f"{result.original_lines - result.final_lines} lines removed"
            )

    if failed:
        logger.warning("Failed files:")
        for result in failed:
            logger.warning(f"  {result.file_path.relative_to(Path.cwd())}: {result.error}")


def main(
    root_dir: str = ".",
    num_workers: int = None,
    keep_backups: bool = True,
    dry_run: bool = False,
) -> int:
    root_path = Path(root_dir)

    if not root_path.exists():
        logger.error(f"Root directory not found: {root_path}")
        return 1

    logger.info(f"Scanning for C/C++ files in {root_path}...")
    source_files = find_source_files(root_path)

    if not source_files:
        logger.warning("No C/C++ source files found.")
        return 0

    logger.info(f"Found {len(source_files)} source files")
    logger.info(f"File types: .h, .hpp, .c, .cpp, .cc, .cxx, .hxx")

    if dry_run:
        logger.info("DRY RUN MODE: No files will be modified")

        remover = CommentRemover()
        for file_path in source_files[:3]:
            try:
                content = file_path.read_text(encoding="utf-8")
                cleaned, comments = remover.remove_comments(content)
                logger.info(f"  {file_path.name}: {comments} comments to remove")
            except Exception as e:
                logger.error(f"  {file_path.name}: {e}")
        return 0

    logger.info(f"Using {num_workers or cpu_count()} workers for parallel processing")
    results = process_files_parallel(source_files, num_workers)

    print_summary(results)

    if not keep_backups:
        logger.info("Removing backup files...")
        backup_count = 0
        for result in results:
            if result.success:
                backup_path = result.file_path.with_suffix(result.file_path.suffix + ".bak")
                if backup_path.exists():
                    backup_path.unlink()
                    backup_count += 1
        logger.info(f"Removed {backup_count} backup files")

    failed = [r for r in results if not r.success]
    return 1 if failed else 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Remove comments from C/C++ files recursively")
    parser.add_argument(
        "-r",
        "--root",
        default=".",
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        help="Number of parallel workers (default: CPU count)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Remove .bak backup files after processing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files",
    )

    args = parser.parse_args()
    exit_code = main(
        args.root,
        args.workers,
        keep_backups=not args.no_backup,
        dry_run=args.dry_run,
    )
    sys.exit(exit_code)
