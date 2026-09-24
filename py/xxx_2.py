import tarfile
import zipfile
from multiprocessing.pool import ApplyResult, Pool
from pathlib import Path
from loguru import logger

TAR_EXTENSIONS = (".tar.gz", ".tar.xz", ".tar.zst")
ZIP_EXTENSIONS = (".zip", ".whl")
MAX_WORKERS = 8


def check_tar_integrity(archive_path):
    try:
        if not tarfile.is_tarfile(archive_path):
            return False, f"Invalid tar format: {archive_path.name}"
        with tarfile.open(archive_path, "r:*") as tar:
            tar.getmembers()
        return True, f"Valid: {archive_path.name}"
    except (tarfile.TarError, EOFError) as e:
        return False, f"Corrupted: {archive_path.name} - {type(e).__name__}"
    except Exception as e:
        return False, f"Check failed: {archive_path.name} - {e}"


def check_zip_integrity(archive_path):
    try:
        if not zipfile.is_zipfile(archive_path):
            return False, f"Invalid zip format: {archive_path.name}"
        with zipfile.ZipFile(archive_path, "r") as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                return (
                    False,
                    f"Corrupted: {archive_path.name} - bad member: {bad_member}",
                )
        return True, f"Valid: {archive_path.name}"
    except (zipfile.BadZipFile, EOFError) as e:
        return False, f"Corrupted: {archive_path.name} - {type(e).__name__}"
    except Exception as e:
        return False, f"Check failed: {archive_path.name} - {e}"


def check_integrity(archive_path):
    if archive_path.suffix.lower() == ".zip" or archive_path.name.lower().endswith(".whl"):
        return check_zip_integrity(archive_path)
    return check_tar_integrity(archive_path)


def extract_archive(archive_path):
    try:
        if archive_path.suffix.lower() == ".zip" or archive_path.name.lower().endswith(".whl"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(path=archive_path.parent)
        else:
            with tarfile.open(archive_path, "r:*") as tar:
                tar.extractall(path=archive_path.parent, filter="data")
        archive_path.unlink()
        return archive_path, True, f"Extracted: {archive_path.name}"
    except Exception as e:
        return archive_path, False, f"Extract failed: {archive_path.name} - {e}"


def find_archives(cwd):
    archives = []
    for ext in TAR_EXTENSIONS:
        archives.extend(cwd.glob(f"*{ext}"))
    for ext in ZIP_EXTENSIONS:
        archives.extend(cwd.glob(f"*{ext}"))
    return sorted(set(archives))


def _collect_results(
    results,
):
    return [r.get() for r in results]


def _collect_extract_results(
    results,
):
    return [r.get() for r in results]


def main():
    cwd = Path.cwd()
    archives = find_archives(cwd)
    if not archives:
        print("No archives found in current directory")
        return 0
    print(f"Found {len(archives)} archive(s)\n--- Checking integrity ---")
    valid_archives = []
    with Pool(processes=MAX_WORKERS) as pool:
        check_results = [pool.apply_async(check_integrity, (archive,)) for archive in archives]
        for archive, (is_valid, message) in zip(archives, _collect_results(check_results)):
            print(message)
            if is_valid:
                valid_archives.append(archive)
    if not valid_archives:
        logger.warning("No valid archives to extract")
        return 0
    print(f"\n--- Extracting {len(valid_archives)} valid archive(s) ---")
    failed = []
    with Pool(processes=MAX_WORKERS) as pool:
        extract_results = [pool.apply_async(extract_archive, (archive,)) for archive in valid_archives]
        for path, success, message in _collect_extract_results(extract_results):
            print(message)
            if not success:
                failed.append(path)
    if failed:
        logger.error(f"{len(failed)} extraction(s) failed")
        return 1
    logger.success(f"Successfully extracted {len(valid_archives)} archive(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
