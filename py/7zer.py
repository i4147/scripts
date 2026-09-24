from __future__ import annotations
import logging
import multiprocessing as mp
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
import py7zr

BASE_DIR = Path.cwd()
LOG_FILE = BASE_DIR / "compress.log"
MAX_WORKERS = max(1, mp.cpu_count() - 1)
TAR_SUFFIX = ".tar"
SEVEN_Z_SUFFIX = ".7z"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(processName)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
    )


def choose_best_py7zr_method():
    candidates = []
    comp = getattr(py7zr, "compressor", None)
    if comp is None:
        raise RuntimeError("py7zr.compressor module not found")
    for name in ["LZMA2", "LZMA", "PPMd"]:
        if hasattr(comp, name):
            candidates.append(getattr(comp, name))
    if not candidates:
        raise RuntimeError("No suitable compression algorithms found in py7zr")
    return candidates[0]


BEST_METHOD = choose_best_py7zr_method()


def iter_top_level_entries(base_dir: Path) -> Iterable[Path]:
    script_name = Path(__file__).name if "__file__" in globals() else None
    for p in base_dir.iterdir():
        if p.name == LOG_FILE.name:
            continue
        if script_name and p.name == script_name:
            continue
        if p.suffix in {TAR_SUFFIX, SEVEN_Z_SUFFIX}:
            continue
        yield p


def make_tar_from_dir(src_dir: Path, tar_path: Path) -> None:
    logging.info("Creating tar: %s -> %s", src_dir, tar_path)
    with tarfile.open(tar_path, "w") as tar:
        tar.add(src_dir, arcname=src_dir.name)


def compress_file_to_7z(src_file: Path, out_path: Path) -> None:
    logging.info("Compressing file: %s -> %s", src_file, out_path)
    with py7zr.SevenZipFile(out_path, mode="w", filters=[{"id": BEST_METHOD, "preset": 9}]) as archive:
        archive.write(src_file, arcname=src_file.name)


def remove_path(p: Path) -> None:
    if p.is_dir():
        logging.info("Removing directory: %s", p)
        for child in p.iterdir():
            if child.is_dir():
                remove_path(child)
            else:
                child.unlink(missing_ok=True)
        p.rmdir()
    else:
        logging.info("Removing file: %s", p)
        p.unlink(missing_ok=True)


@dataclass
class TaskResult:
    src: str
    dst: str
    ok: bool
    error: Optional[str] = None


def process_dir(src_dir: Path) -> TaskResult:
    try:
        tar_path = (
            src_dir.with_suffix(src_dir.suffix + TAR_SUFFIX) if src_dir.suffix else Path(str(src_dir) + TAR_SUFFIX)
        )
        make_tar_from_dir(src_dir, tar_path)
        remove_path(src_dir)
        return TaskResult(src=str(src_dir), dst=str(tar_path), ok=True)
    except Exception as e:
        logging.exception("Failed processing directory %s", src_dir)
        return TaskResult(src=str(src_dir), dst="", ok=False, error=str(e))


def process_file(src_file: Path) -> TaskResult:
    try:
        out_path = Path(str(src_file) + SEVEN_Z_SUFFIX)
        compress_file_to_7z(src_file, out_path)
        remove_path(src_file)
        return TaskResult(src=str(src_file), dst=str(out_path), ok=True)
    except Exception as e:
        logging.exception("Failed processing file %s", src_file)
        return TaskResult(src=str(src_file), dst="", ok=False, error=str(e))


def main() -> None:
    setup_logging()
    logging.info("Starting compression in %s", BASE_DIR)
    logging.info("Using %d workers", MAX_WORKERS)
    logging.info("Selected py7zr compression method: %s", BEST_METHOD)
    entries = list(iter_top_level_entries(BASE_DIR))
    dirs = [p for p in entries if p.is_dir()]
    files = [p for p in entries if p.is_file()]
    logging.info("Found %d directories and %d files", len(dirs), len(files))
    results = []
    if dirs:
        with mp.Pool(processes=min(MAX_WORKERS, len(dirs))) as pool:
            results.extend(pool.map(process_dir, dirs))
    if files:
        with mp.Pool(processes=min(MAX_WORKERS, len(files))) as pool:
            results.extend(pool.map(process_file, files))
    ok_count = sum((1 for r in results if r.ok))
    fail_count = len(results) - ok_count
    logging.info("Done. Success: %d, Failed: %d", ok_count, fail_count)
    if fail_count:
        for r in results:
            if not r.ok:
                logging.error("Failed: %s -> %s | %s", r.src, r.dst, r.error)


if __name__ == "__main__":
    main()
