from __future__ import annotations
import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dh import MIME2EXT, SHEBANG_MAP
from loguru import logger

logger.remove()
logger.add(
    sys.stderr,
    format="<level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
)
PROTECTED_EXTENSIONS = {
    ".css",
    ".js",
    ".min.js",
    ".min.css",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
}


def detect_with_pure_magic(file_path: Path) -> str | None:
    try:
        import magic

        mime = magic.Magic(mime=True)
        mime_type = mime.from_file(str(file_path))
        return _mime_to_ext(mime_type)
    except Exception as e:
        logger.debug(f"pure-magic failed for {file_path.name}: {e}")
        return None


def detect_with_python_magic(file_path: Path) -> str | None:
    try:
        import magic

        mime_type = magic.from_file(str(file_path), mime=True)
        return _mime_to_ext(mime_type)
    except Exception as e:
        logger.debug(f"python-magic failed for {file_path.name}: {e}")
        return None


def detect_with_filetype(file_path: Path) -> str | None:
    try:
        import filetype

        kind = filetype.guess(str(file_path))
        if kind:
            return f".{kind.extension}"
        return None
    except Exception as e:
        logger.debug(f"filetype failed for {file_path.name}: {e}")
        return None


def detect_with_file_command(file_path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["file", "--brief", "--mime-type", str(file_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            mime_type = result.stdout.strip()
            return _mime_to_ext(mime_type)
        return None
    except Exception as e:
        logger.debug(f"file command failed for {file_path.name}: {e}")
        return None


def _mime_to_ext(mime_type: str) -> str | None:
    if mime_type in MIME2EXT:
        exts = MIME2EXT[mime_type]
        return exts[0] if isinstance(exts, list) else exts
    return None


def detect_shebang_ext(file_path: Path) -> str | None:
    try:
        with open(file_path, "rb") as f:
            first_line = f.readline()
        if first_line.startswith(b"#!"):
            shebang = first_line.decode("utf-8", errors="ignore").strip()
            for key, ext in SHEBANG_MAP.items():
                if key in shebang:
                    return ext
        return None
    except Exception as e:
        logger.debug(f"shebang detection failed for {file_path.name}: {e}")
        return None


def detect_extension(file_path: Path) -> str | None:
    detectors = [
        detect_with_pure_magic,
        detect_with_python_magic,
        detect_with_filetype,
        detect_with_file_command,
    ]
    for detector in detectors:
        ext = detector(file_path)
        if ext:
            return ext
    return None


def check_file(file_path: Path, auto_fix: bool = False) -> tuple[Path, bool, str | None, str | None]:
    if not file_path.is_file():
        return file_path, False, None, None
    current_ext = file_path.suffix.lower()
    if not current_ext:
        detected_ext = detect_shebang_ext(file_path)
        if detected_ext:
            if auto_fix:
                new_name = file_path.with_suffix(detected_ext)
                try:
                    file_path.rename(new_name)
                    logger.info(f"Renamed: {file_path.name} → {new_name.name} (shebang-based)")
                    return new_name, True, None, detected_ext
                except Exception as e:
                    logger.error(f"Failed to rename {file_path.name}: {e}")
                    return file_path, False, None, detected_ext
            else:
                logger.warning(f"No extension found; shebang suggests {detected_ext}: {file_path.name}")
                return file_path, True, None, detected_ext
        return file_path, False, None, None
    detected_ext = detect_extension(file_path)
    if not detected_ext:
        return file_path, False, None, None
    if current_ext == detected_ext:
        return file_path, False, None, None
    if current_ext in PROTECTED_EXTENSIONS and detected_ext == ".txt":
        logger.debug(f"Protected extension; skipping: {file_path.name}")
        return file_path, False, None, None
    if auto_fix:
        new_name = file_path.with_suffix(detected_ext)
        try:
            file_path.rename(new_name)
            logger.info(f"Renamed: {file_path.name} → {new_name.name} ({current_ext} → {detected_ext})")
            return new_name, True, current_ext, detected_ext
        except Exception as e:
            logger.error(f"Failed to rename {file_path.name}: {e}")
            return file_path, True, current_ext, detected_ext
    else:
        logger.warning(f"Mismatch: {file_path.name} ({current_ext} → {detected_ext})")
        return file_path, True, current_ext, detected_ext


def main():
    parser = argparse.ArgumentParser(description="Detect and fix file extension mismatches")
    parser.add_argument(
        "-a",
        "--auto-fix",
        action="store_true",
        help="Automatically fix extension mismatches",
    )
    parser.add_argument(
        "-d",
        "--directory",
        type=Path,
        default=Path.cwd(),
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    args = parser.parse_args()
    logger.info(f"Scanning: {args.directory}")
    if args.auto_fix:
        logger.info("Auto-fix enabled")
    files = list(args.directory.rglob("*"))
    files = [f for f in files if f.is_file()]
    mismatches = 0
    fixed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(check_file, file_path, args.auto_fix): file_path for file_path in files}
        for future in as_completed(futures):
            try:
                _file_path, is_mismatch, old_ext, new_ext = future.result()
                if is_mismatch:
                    mismatches += 1
                    if args.auto_fix and old_ext and new_ext:
                        fixed += 1
            except Exception as e:
                logger.error(f"Error processing file: {e}")
    logger.info(f"Total files scanned: {len(files)}")
    logger.info(f"Mismatches found: {mismatches}")
    if args.auto_fix:
        logger.info(f"Files fixed: {fixed}")


if __name__ == "__main__":
    main()
