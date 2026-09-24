import shutil
import subprocess
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path
from typing import Any
from loguru import logger


@dataclass
class ExtractionStats:
    output_dir = None
    extracted_files = 0
    error_message = None
    original_size = 0

    def __str__(self):
        size_mb = self.original_size / (1024 * 1024)
        status_icon = "✓" if self.status == "success" else "✗" if self.status == "failed" else "○"
        result = f"{status_icon} {self.archive_path.name} [{size_mb:.1f}MB] - {self.status}"
        if self.status == "success":
            result += f" ({self.extracted_files} files, {self.extraction_time:.1f}s)"
            if self.output_dir:
                result += f" → {self.output_dir.name}"
        elif self.status == "failed":
            result += f" - {self.error_message}"
        return result


class ArchiveExtractor:
    EXTRACTION_COMMANDS = {
        ".7z": ["7z", "x", "-y", "-o"],
        ".zip": ["unzip", "-o"],
        ".rar": ["unrar", "x", "-y"],
        ".tar": ["tar", "-xf"],
        ".tar.gz": ["tar", "-xzf"],
        ".tgz": ["tar", "-xzf"],
        ".tar.bz2": ["tar", "-xjf"],
        ".tbz2": ["tar", "-xjf"],
        ".tar.xz": ["tar", "-xJf"],
        ".txz": ["tar", "-xJf"],
        ".gz": ["gunzip", "-f"],
        ".bz2": ["bunzip2", "-f"],
        ".xz": ["unxz", "-f"],
        ".lz4": ["lz4", "-d", "-f"],
        ".lzma": ["unlzma", "-f"],
        ".zst": ["unzstd", "-f"],
        ".cab": ["cabextract"],
        ".arj": ["arj", "x", "-y"],
        ".ace": ["unace", "x"],
    }
    SINGLE_FILE_EXTENSIONS = {".gz", ".bz2", ".xz", ".lz4", ".lzma", ".zst"}

    def __init__(self, current_dir):
        self.current_dir = current_dir
        self._check_available_tools()

    def _check_available_tools(self):
        available = {}
        for ext, cmd in self.EXTRACTION_COMMANDS.items():
            tool = cmd[0]
            if shutil.which(tool):
                available[ext] = True
            else:
                available[ext] = False
        return available

    def _check_if_single_file_archive(self, archive_path):
        if archive_path.suffix.lower() in self.SINGLE_FILE_EXTENSIONS:
            return True
        try:
            suffix = archive_path.suffix.lower()
            if suffix == ".zip":
                result = subprocess.run(
                    ["unzip", "-l", str(archive_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    entries = []
                    for line in lines[3:-2]:
                        parts = line.strip().split()
                        if len(parts) >= 4:
                            entries.append(" ".join(parts[3:]))
                    if entries:
                        first_parts = set()
                        for entry in entries:
                            parts = Path(entry).parts
                            if parts:
                                first_parts.add(parts[0])
                        return len(first_parts) == 1 and not all("/" not in e for e in entries)
            elif suffix in [
                ".tar",
                ".tar.gz",
                ".tar.bz2",
                ".tar.xz",
                ".tgz",
                ".tbz2",
                ".txz",
            ]:
                result = subprocess.run(
                    ["tar", "-tf", str(archive_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    entries = [line.strip() for line in result.stdout.split("\n") if line.strip()]
                    if entries:
                        first_parts = set()
                        for entry in entries:
                            parts = Path(entry).parts
                            if parts:
                                first_parts.add(parts[0])
                        return len(first_parts) == 1 and not all("/" not in e for e in entries)
        except (subprocess.TimeoutExpired, Exception):
            pass
        return False

    def _get_output_directory(self, archive_path):
        stem = archive_path.name
        for ext in [".tar.gz", ".tar.bz2", ".tar.xz", ".tar.lz4"]:
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
                break
        else:
            stem = archive_path.stem
        return self.current_dir / stem

    def _count_files(self, directory):
        try:
            return sum(1 for _ in directory.rglob("*") if _.is_file())
        except Exception:
            return 0

    def extract_archive(self, archive_path):
        start_time = time.time()
        original_size = archive_path.stat().st_size if archive_path.exists() else 0
        stats = ExtractionStats(
            archive_path=archive_path,
            status="failed",
            extraction_time=0,
            original_size=original_size,
        )
        archive_name = archive_path.name.lower()
        ext = None
        for possible_ext in sorted(self.EXTRACTION_COMMANDS.keys(), key=len, reverse=True):
            if archive_name.endswith(possible_ext):
                ext = possible_ext
                break
        if not ext:
            stats.status = "skipped"
            stats.error_message = f"Unsupported format: {archive_path.suffix}"
            stats.extraction_time = time.time() - start_time
            return stats
        tool = self.EXTRACTION_COMMANDS[ext][0]
        if not shutil.which(tool):
            stats.status = "failed"
            stats.error_message = f"Tool '{tool}' not found"
            stats.extraction_time = time.time() - start_time
            return stats
        try:
            needs_subdir = self._check_if_single_file_archive(archive_path)
            output_dir = self._get_output_directory(archive_path) if needs_subdir else self.current_dir
            if needs_subdir:
                output_dir.mkdir(exist_ok=True)
            cmd = list(self.EXTRACTION_COMMANDS[ext])
            if ext == ".7z":
                cmd.append(str(archive_path))
                cmd[-2] = f"-o{output_dir}"
            elif ext == ".zip":
                cmd.extend([str(archive_path), "-d", str(output_dir)])
            elif ext in [
                ".tar",
                ".tar.gz",
                ".tar.bz2",
                ".tar.xz",
                ".tgz",
                ".tbz2",
                ".txz",
            ]:
                cmd.extend(["-C", str(output_dir), str(archive_path)])
            elif ext == ".rar":
                cmd.extend([str(archive_path), str(output_dir)])
            elif ext == ".lz4":
                output_file = output_dir / archive_path.stem
                cmd.extend([str(archive_path), str(output_file)])
            elif ext in [".gz", ".bz2", ".xz", ".lzma", ".zst"]:
                temp_archive = output_dir / archive_path.name
                shutil.copy2(archive_path, temp_archive)
                cmd.append(str(temp_archive))
                cwd = output_dir
                result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
                if result.returncode == 0:
                    temp_archive.unlink(missing_ok=True)
                    stats.status = "success"
                    stats.output_dir = output_dir
                    stats.extracted_files = self._count_files(output_dir)
                    stats.extraction_time = time.time() - start_time
                    archive_path.unlink()
                    return stats
                else:
                    raise subprocess.CalledProcessError(
                        result.returncode,
                        cmd,
                        output=result.stdout,
                        stderr=result.stderr,
                    )
            else:
                cmd.append(str(archive_path))
                if output_dir != self.current_dir:
                    cmd.append(str(output_dir))
            if ext not in [".gz", ".bz2", ".xz", ".lzma", ".zst"]:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=self.current_dir,
                )
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(
                        result.returncode,
                        cmd,
                        output=result.stdout,
                        stderr=result.stderr,
                    )
            if needs_subdir:
                extracted_count = self._count_files(output_dir)
            else:
                extracted_count = self._count_files(self.current_dir)
            stats.status = "success"
            stats.output_dir = output_dir if needs_subdir else None
            stats.extracted_files = extracted_count
            stats.extraction_time = time.time() - start_time
            try:
                archive_path.unlink()
            except Exception as e:
                stats.error_message = f"Extracted but couldn't remove original: {e}"
        except subprocess.CalledProcessError as e:
            stats.error_message = e.stderr.strip() if e.stderr else str(e)
            stats.extraction_time = time.time() - start_time
        except subprocess.TimeoutExpired:
            stats.error_message = "Extraction timed out (300s)"
            stats.extraction_time = time.time() - start_time
        except Exception as e:
            stats.error_message = str(e)
            stats.extraction_time = time.time() - start_time
        return stats


def find_archives(directory):
    archive_extensions = {
        ".7z",
        ".zip",
        ".rar",
        ".tar",
        ".tar.gz",
        ".tar.bz2",
        ".tar.xz",
        ".tgz",
        ".tbz2",
        ".txz",
        ".gz",
        ".bz2",
        ".xz",
        ".lz4",
        ".lzma",
        ".zst",
        ".cab",
        ".arj",
        ".ace",
    }
    archives = []
    for item in directory.iterdir():
        if item.is_file():
            name_lower = item.name.lower()
            for ext in archive_extensions:
                if name_lower.endswith(ext):
                    archives.append(item)
                    break
    return archives


def main():
    current_dir = Path.cwd()
    print(f"Scanning for archivesin: {current_dir}")
    archives = find_archives(current_dir)
    if not archives:
        print("No archive files found.")
        return 0
    print(f"Found {len(archives)} archive(s):")
    for archive in archives:
        size_mb = archive.stat().st_size / (1024 * 1024)
        print(f"  • {archive.name} ({size_mb:.1f} MB)")
    max_workers = 8
    print(f"Processing with {max_workers} parallel worker(s)...")
    extractor = ArchiveExtractor(current_dir)
    results = []
    start_time = time.time()
    with Pool(processes=max_workers) as pool:
        async_results = []
        for archive in archives:
            async_result = pool.apply_async(extractor.extract_archive, (archive,))
            async_results.append((async_result, archive))
        for async_result, archive in async_results:
            try:
                result = async_result.get()
                results.append(result)
                print(str(result))
            except Exception as e:
                logger.error(f"✗ {archive.name} - Worker error: {e}")
    total_time = time.time() - start_time
    successful = sum(1 for r in results if r.status == "success")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")
    print(f"\n{'=' * 40}")
    print("SUMMARY")
    print(f"{'=' * 40}")
    print(f"Total archives: {len(archives)}")
    print(f"✓ Successfully extracted: {successful}")
    print(f"✗ Failed: {failed}")
    print(f"○ Skipped: {skipped}")
    print(f"Total time: {total_time:.1f}s")
    if results:
        print("\nDetailed results:")
        for result in results:
            print(f"  {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
