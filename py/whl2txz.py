from __future__ import annotations

import argparse
import logging
import sys
import tarfile
import traceback
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def convert_zip_time_to_timestamp(
    date_time: tuple[int, int, int, int, int, int],
) -> float:
    try:
        dt = datetime(*date_time)
        return dt.timestamp()
    except (ValueError, TypeError):
        return datetime.now().timestamp()


def get_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 1
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def preserve_zip_metadata(zip_member: zipfile.ZipInfo, tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
    tarinfo.size = zip_member.file_size
    if zip_member.date_time:
        tarinfo.mtime = convert_zip_time_to_timestamp(zip_member.date_time)
    if zip_member.external_attr:
        unix_permissions = zip_member.external_attr >> 16 & 4095
        if unix_permissions:
            tarinfo.mode = unix_permissions
        else:
            tarinfo.mode = 493 if zip_member.filename.endswith((".sh", ".py", ".exe")) else 420
    else:
        tarinfo.mode = 420
    tarinfo.type = tarfile.REGTYPE
    tarinfo.uid = 0
    tarinfo.gid = 0
    tarinfo.uname = "root"
    tarinfo.gname = "root"
    return tarinfo


def preserve_tar_metadata(tarinfo: tarfile.TarInfo, zipinfo: zipfile.ZipInfo) -> zipfile.ZipInfo:
    if hasattr(tarinfo, "mtime") and tarinfo.mtime:
        dt = datetime.fromtimestamp(tarinfo.mtime)
        zipinfo.date_time = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    if hasattr(tarinfo, "mode") and tarinfo.mode:
        zipinfo.external_attr = (tarinfo.mode & 65535) << 16
    return zipinfo


def convert_whl_to_tarxz(path: Path, remove_original: bool = False) -> tuple[bool, str, Path | None]:
    try:
        if not path.exists() or not path.is_file():
            return False, f"Invalid file: {path}", None
        if path.suffix.lower() != ".whl":
            return False, f"Not a wheel file: {path.name}", None
        output_path = path.with_suffix(".tar.xz")
        if output_path.exists():
            output_path = get_unique_path(output_path)
            logger.info(f"Target exists, using: {output_path.name}")
        converted_count = 0
        failed_members = []
        with zipfile.ZipFile(path, "r") as zip_file:
            bad_file = zip_file.testzip()
            if bad_file:
                return False, f"Corrupt ZIP file: {bad_file}", None
            with tarfile.open(output_path, "w:xz") as tar_file:
                for member in zip_file.infolist():
                    if member.is_dir():
                        continue
                    try:
                        with zip_file.open(member) as source:
                            tarinfo = tarfile.TarInfo(name=member.filename)
                            tarinfo = preserve_zip_metadata(member, tarinfo)
                            tar_file.addfile(tarinfo, source)
                            converted_count += 1
                    except Exception as e:
                        failed_members.append(f"{member.filename}: {e}")
        if failed_members:
            logger.warning(f"Failed to convert {len(failed_members)} files in {path.name}")
        if output_path.exists() and output_path.stat().st_size > 0:
            if remove_original:
                try:
                    path.unlink()
                    logger.info(f"Removed original: {path.name}")
                except Exception as e:
                    logger.error(f"Failed to remove original file {path.name}: {e}")
                    return (
                        False,
                        f"Conversion succeeded but failed to remove original: {e}",
                        output_path,
                    )
            return (True, f"Converted {converted_count} files to tar.xz", output_path)
        else:
            return False, "Output file is empty or missing", None
    except Exception as e:
        return False, f"Conversion error: {e}", None


def convert_tarxz_to_whl(path: Path, remove_original: bool = False) -> tuple[bool, str, Path | None]:
    try:
        if not path.exists() or not path.is_file():
            return False, f"Invalid file: {path}", None
        if not (path.suffix == ".xz" and path.stem.endswith(".tar")):
            return False, f"Not a tar.xz file: {path.name}", None
        stem = path.stem
        stem = stem.removesuffix(".tar")
        output_path = path.parent / f"{stem}.whl"
        if output_path.exists():
            output_path = get_unique_path(output_path)
            logger.info(f"Target exists, using: {output_path.name}")
        converted_count = 0
        with (
            tarfile.open(path, "r:xz") as tar_file,
            zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zip_file,
        ):
            for member in tar_file.getmembers():
                if member.isdir():
                    continue
                try:
                    file_content = tar_file.extractfile(member)
                    if file_content:
                        zipinfo = zipfile.ZipInfo(filename=member.name)
                        zipinfo = preserve_tar_metadata(member, zipinfo)
                        zipinfo.file_size = member.size
                        zip_file.writestr(zipinfo, file_content.read())
                        converted_count += 1
                        file_content.close()
                except Exception as e:
                    logger.error(f"Failed to convert {member.name}: {e}")
                    return (
                        False,
                        f"Failed to convert member {member.name}: {e}",
                        None,
                    )
        if output_path.exists() and output_path.stat().st_size > 0:
            try:
                with zipfile.ZipFile(output_path, "r") as test_zip:
                    bad_file = test_zip.testzip()
                    if bad_file:
                        return (False, f"Created corrupt zip file: {bad_file}", None)
            except Exception as e:
                return False, f"Verification failed: {e}", None
            if remove_original:
                try:
                    path.unlink()
                    logger.info(f"Removed original: {path.name}")
                except Exception as e:
                    logger.error(f"Failed to remove original file {path.name}: {e}")
                    return (
                        False,
                        f"Conversion succeeded but failed to remove original: {e}",
                        output_path,
                    )
            return (True, f"Converted {converted_count} files to wheel", output_path)
        else:
            return False, "Output file is empty or missing", None
    except tarfile.TarError as e:
        return False, f"Tar error: {e}", None
    except Exception as e:
        return False, f"Conversion error: {e}", None


def process_file(path: Path, remove_original: bool = False) -> tuple[bool, str, Path | None]:
    path = Path(path)
    if not path.exists():
        return False, f"File not found: {path}", None
    if path.suffix.lower() == ".whl":
        logger.info(f"Converting wheel to tar.xz: {path.name}")
        return convert_whl_to_tarxz(path, remove_original)
    elif path.suffix == ".xz" and (path.stem.endswith(".tar") or ".tar." in str(path)):
        logger.info(f"Converting tar.xz to wheel: {path.name}")
        return convert_tarxz_to_whl(path, remove_original)
    else:
        return (
            False,
            f"Unsupported file type: {path.suffix} (only .whl or .tar.xz)",
            None,
        )


def find_convertible_files(directory: Path, recursive: bool = False) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    convertible_files = []
    whl_pattern = "**/*.whl" if recursive else "*.whl"
    convertible_files.extend(directory.glob(whl_pattern))
    tarxz_pattern = "**/*.tar.xz" if recursive else "*.tar.xz"
    convertible_files.extend(directory.glob(tarxz_pattern))
    return convertible_files


def process_single_file(args):
    file_path, remove_original = args
    success, message, output_path = process_file(file_path, remove_original)
    return file_path, success, message, output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bidirectional converter between .whl and .tar.xz files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s package.whl
  %(prog)s package.tar.xz
  %(prog)s *.whl
  %(prog)s /path/to/dir
  %(prog)s --recursive
  %(prog)s --remove-original
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument("-r", "--recursive", action="store_true", help="Search directories recursively")
    parser.add_argument(
        "--remove-original",
        action="store_true",
        help="Remove original files after successful conversion",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="Number of parallel jobs (default: CPU count)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress non-error output")
    args = parser.parse_args()
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    elif args.quiet:
        logger.setLevel(logging.ERROR)
    convertible_files = []
    for input_path in args.paths:
        path = Path(input_path)
        if not path.exists():
            logger.error(f"Path does not exist: {path}")
            continue
        if path.is_file():
            if path.suffix.lower() == ".whl" or (path.suffix == ".xz" and ".tar" in str(path)):
                convertible_files.append(path)
            else:
                logger.warning(f"Skipping unsupported file: {path}")
        elif path.is_dir():
            found = find_convertible_files(path, args.recursive)
            convertible_files.extend(found)
            logger.info(f"Found {len(found)} convertible files in {path}")
        else:
            logger.error(f"Invalid path: {path}")
    if not convertible_files:
        if args.paths == ["."]:
            logger.info("No .whl or .tar.xz files found in current directory")
        else:
            logger.error("No convertible files found")
        return 1
    logger.info(f"Processing {len(convertible_files)} file(s)")
    if args.remove_original:
        logger.info("Original files will be removed after successful conversion")
    success_count = 0
    failure_count = 0
    results = []
    if len(convertible_files) == 1:
        success, message, output_path = process_file(convertible_files[0], args.remove_original)
        results.append((convertible_files[0], success, message, output_path))
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as executor:
            file_args = [(f, args.remove_original) for f in convertible_files]
            future_to_file = {executor.submit(process_single_file, file_arg): file_arg[0] for file_arg in file_args}
            for future in as_completed(future_to_file):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    file_path = future_to_file[future]
                    results.append((file_path, False, f"Execution failed: {e}", None))
                    logger.error(f"Failed to process {file_path.name}: {e}")
    print("\n" + "=" * 40)
    print("CONVERSION RESULTS")
    print("-" * 40)
    for file_path, success, message, output_path in results:
        if success:
            file_path.unlink()
            success_count += 1
            status = "✓ OK"
            input_type = "whl" if file_path.suffix == ".whl" else "tar.xz"
            output_type = "tar.xz" if output_path and output_path.suffix == ".xz" else "whl"
            size_info = ""
            if output_path and output_path.exists():
                size_kb = output_path.stat().st_size / 1024
                size_info = f" ({size_kb:.1f} KB)"
            print(
                f"{status} {file_path.name} [{input_type}] → {output_path.name if output_path else 'unknown'} [{
                    output_type
                }]{size_info}"
            )
            if args.verbose:
                print(f"   {message}")
        else:
            failure_count += 1
            status = "✗ FAIL"
            print(f"{status} {file_path.name}: {message}")
    print("-" * 40)
    print(f"Summary: {success_count} successful, {failure_count} failed")
    if args.remove_original and success_count > 0:
        print("✓ Original files were removed after successful conversion")
    return 0 if failure_count == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}\n{traceback.format_exc()}")
        sys.exit(1)
