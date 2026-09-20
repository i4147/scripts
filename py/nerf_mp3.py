from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from dh import fsz


class Colors:
    HEADER = "\033[95m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"
    CLEAR_LINE = "\033[2K\r"


@dataclass
class ConversionStats:
    file_path: Path
    original_bitrate: int
    new_bitrate: int
    original_size: int
    new_size: int
    success: bool
    error_message: str = ""
    duration: float = 0.0


def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"{Colors.RED}✗ ffmpeg/ffprobe is required but not installed.{Colors.END}")
        sys.exit(1)


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 400:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.0f}s"


def get_audio_info(mp3_file: Path) -> tuple[int | None, int | None]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(mp3_file),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        info = json.loads(result.stdout)
        format_info = info.get("format", {})
        bitrate = int(format_info.get("bit_rate", 0))
        size = int(format_info.get("size", mp3_file.stat().st_size))
        if bitrate > 0:
            return bitrate // 1000, size
        else:
            duration = float(format_info.get("duration", 0))
            if duration > 0 and size > 0:
                estimated_bitrate = int((size * 8) / (duration * 400))
                return estimated_bitrate, size
            return None, None
    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
        OSError,
    ):
        return None, None


def convert_single_file(mp3_file: Path, base_dir: Path) -> ConversionStats:
    start_time = time.time()
    rel_path = mp3_file.relative_to(base_dir)
    original_bitrate, original_size = get_audio_info(mp3_file)
    if original_bitrate is None:
        return ConversionStats(
            file_path=rel_path,
            original_bitrate=0,
            new_bitrate=0,
            original_size=0,
            new_size=0,
            success=False,
            error_message="Could not determine bitrate",
            duration=0,
        )
    new_bitrate = original_bitrate // 2
    if new_bitrate < 8:
        return ConversionStats(
            file_path=rel_path,
            original_bitrate=original_bitrate,
            new_bitrate=new_bitrate,
            original_size=original_size,
            new_size=0,
            success=False,
            error_message=f"Calculated bitrate too low ({new_bitrate} kbps)",
            duration=0,
        )
    temp_file = mp3_file.with_suffix(".tmp_convert.mp3")
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mp3_file),
                "-codec:a",
                "libmp3lame",
                "-ab",
                f"{new_bitrate}k",
                str(temp_file),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        duration = time.time() - start_time
        if result.returncode == 0 and temp_file.exists():
            new_size = temp_file.stat().st_size
            temp_file.replace(mp3_file)
            return ConversionStats(
                file_path=rel_path,
                original_bitrate=original_bitrate,
                new_bitrate=new_bitrate,
                original_size=original_size,
                new_size=new_size,
                success=True,
                duration=duration,
            )
        else:
            temp_file.unlink(missing_ok=True)
            return ConversionStats(
                file_path=rel_path,
                original_bitrate=original_bitrate,
                new_bitrate=new_bitrate,
                original_size=original_size,
                new_size=0,
                success=False,
                error_message=f"ffmpeg error: {result.stderr[:100]}",
                duration=duration,
            )
    except Exception as e:
        duration = time.time() - start_time
        temp_file.unlink(missing_ok=True)
        return ConversionStats(
            file_path=rel_path,
            original_bitrate=original_bitrate,
            new_bitrate=new_bitrate,
            original_size=original_size,
            new_size=0,
            success=False,
            error_message=str(e)[:100],
            duration=duration,
        )


def print_file_result(stat: ConversionStats, index: int, total: int):
    status_icon = f"{Colors.GREEN}✓{Colors.END}" if stat.success else f"{Colors.RED}✗{Colors.END}"
    if stat.success:
        size_saved = stat.original_size - stat.new_size
        size_percent = (size_saved / stat.original_size * 40) if stat.original_size > 0 else 0
        print(f"{Colors.CLEAR_LINE}{status_icon} [{index}/{total}] {Colors.CYAN}{stat.file_path}{Colors.END}")
        print(
            f"  {Colors.DIM}{fsz(stat.original_size)} → {fsz(stat.new_size)} "
            f"({Colors.GREEN}-{size_percent:.1f}%{Colors.END}) | "
            f"{stat.original_bitrate} kbps → {Colors.YELLOW}{stat.new_bitrate} kbps{Colors.END} | "
            f"{format_duration(stat.duration)}{Colors.END}"
        )
    else:
        print(f"{Colors.CLEAR_LINE}{status_icon} [{index}/{total}] {Colors.RED}{stat.file_path}{Colors.END}")
        print(f"  {Colors.RED}Error: {stat.error_message}{Colors.END}")


def print_final_summary(stats: list[ConversionStats], total_duration: float):
    successful = [s for s in stats if s.success]
    failed = [s for s in stats if not s.success]
    total_original = sum(s.original_size for s in successful)
    total_new = sum(s.new_size for s in successful)
    total_saved = total_original - total_new
    print(f"\n{'─' * 40}")
    print(f"{Colors.BOLD}Conversion Summary{Colors.END}")
    print(f"{'─' * 40}")
    print(f"Total files: {len(stats)}")
    print(f"{Colors.GREEN}Successful:{Colors.END} {len(successful)}")
    print(f"{Colors.RED}Failed:{Colors.END} {len(failed)}")
    if successful:
        print(f"\n{Colors.BOLD}Space saved:{Colors.END}")
        print(f"  Before: {fsz(total_original)}")
        print(f"  After:  {fsz(total_new)}")
        print(f"  Saved:  {Colors.GREEN}{fsz(total_saved)} ({total_saved / total_original * 40:.1f}%){Colors.END}")
    print(f"\n{Colors.BOLD}Total time:{Colors.END} {format_duration(total_duration)}")
    print(f"{'─' * 40}")


def find_mp3_files(directories: list[Path]) -> list[Path]:
    mp3_files = []
    for directory in directories:
        if not directory.exists():
            print(f"{Colors.YELLOW}Warning: Directory not found: {directory}{Colors.END}")
            continue
        if not directory.is_dir():
            print(f"{Colors.YELLOW}Warning: Not a directory: {directory}{Colors.END}")
            continue
        for ext in ["*.mp3", "*.MP3", "*.Mp3"]:
            mp3_files.extend(directory.rglob(ext))
    seen = set()
    unique_files = []
    for f in mp3_files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(f)
    return sorted(unique_files)


def process_directory(directory: Path, max_workers: int = 4):
    mp3_files = find_mp3_files([directory])
    if not mp3_files:
        print(f"{Colors.YELLOW}No MP3 files found in {directory}{Colors.END}")
        return
    print(f"{Colors.BOLD}Found {len(mp3_files)} MP3 file(s) in {directory}{Colors.END}\n")
    stats = []
    start_time = time.time()
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(convert_single_file, mp3_file, directory): mp3_file for mp3_file in mp3_files}
        for i, future in enumerate(as_completed(future_to_file), 1):
            stat = future.result()
            stats.append(stat)
            print_file_result(stat, i, len(mp3_files))
    total_duration = time.time() - start_time
    stats.sort(key=lambda s: str(s.file_path))
    failed = [s for s in stats if not s.success]
    if failed:
        print(f"\n{Colors.RED}{Colors.BOLD}Failed conversions:{Colors.END}")
        for stat in failed:
            print(f"  {Colors.RED}✗{Colors.END} {stat.file_path}: {stat.error_message}")
    print_final_summary(stats, total_duration)


def main():
    parser = argparse.ArgumentParser(
        description="Convert MP3 files to half their original bitrate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s ~/music
  %(prog)s dir1 dir2 dir3
  %(prog)s -w 8 ~/music
        """,
    )
    parser.add_argument(
        "directories",
        nargs="*",
        type=Path,
        default=[Path.cwd()],
        help="Directories to process (default: current directory)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=min(4, os.cpu_count() or 1),
        help="Number of parallel workers (default: min(4, CPU cores))",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    args = parser.parse_args()
    if args.no_color:
        for attr in dir(Colors):
            if not attr.startswith("__"):
                setattr(Colors, attr, "")
    check_ffmpeg()
    print(f"{Colors.HEADER}{Colors.BOLD}MP3 Bitrate Halver{Colors.END}")
    print(f"{Colors.DIM}Using {args.workers} parallel worker(s){Colors.END}\n")
    for directory in args.directories:
        process_directory(directory, max_workers=args.workers)
        if len(args.directories) > 1:
            print()


if __name__ == "__main__":
    raise SystemExit(main())
