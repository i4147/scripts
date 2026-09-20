
from __future__ import annotations

import argparse
import concurrent.futures
import os
import shutil
import sys
from pathlib import Path

import zstandard as zstd


try:
    from dh import cprint, gsz
except Exception:

    def gsz(p: Path | str) -> int:
        try:
            return int(Path(p).stat().st_size)
        except Exception:
            return 0

    def cprint(msg: str) -> None:
        print(msg)


COMPRESSED_EXTS = {".xz", ".br", ".7z", ".zip", ".gz", ".bz2", ".zst", ".whl"}


def human_size(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024.0:
            return f"{size:3.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PiB"


def should_compress_entry(entry: os.DirEntry) -> bool:
    try:
        if not entry.is_file(follow_symlinks=False):
            return False
        suffix = Path(entry.name).suffix
        if suffix in COMPRESSED_EXTS:
            return False

        return entry.stat(follow_symlinks=False).st_size > 0
    except (OSError, PermissionError):
        return False


def list_dirs(path: Path) -> list[Path]:
    out = []
    with os.scandir(path) as it:
        for entry in it:
            try:
                if entry.is_dir(follow_symlinks=False):
                    out.append(Path(entry.path))
            except Exception:
                continue
    return sorted(out)


def list_files(path: Path) -> list[Path]:
    out = []
    with os.scandir(path) as it:
        for entry in it:
            try:
                if should_compress_entry(entry):
                    out.append(Path(entry.path))
            except Exception:
                continue
    return sorted(out)


def compress_folder_sync(folder_path: Path, output_base_name: str, fmt: str = "tar") -> tuple[bool, str | None]:
    try:
        archive = shutil.make_archive(output_base_name, fmt, str(folder_path))
        return True, archive
    except Exception as e:
        return False, str(e)


def compress_file_sync(path: Path, level: int, zstd_threads: int) -> dict:
    result = {
        "path": path,
        "success": False,
        "skipped": False,
        "error": None,
        "before": 0,
        "after": 0,
    }
    dst = path.with_suffix(path.suffix + ".zst")
    if dst.exists():
        result["skipped"] = True
        return result
    try:
        st = path.stat()
        before = st.st_size
        if before == 0:
            result["skipped"] = True
            return result
        result["before"] = before

        cctx = zstd.ZstdCompressor(level=level, threads=zstd_threads)

        with path.open("rb") as fin, dst.open("wb") as fout:
            cctx.copy_stream(fin, fout)

        after = dst.stat().st_size if dst.exists() else 0
        result["after"] = after

        if after == 0:
            try:
                dst.unlink(missing_ok=True)
            except Exception:
                pass
            result["error"] = "empty destination"
            return result

        try:
            path.unlink()
        except Exception as e:
            result["error"] = f"compressed but failed to delete original: {e}"
            result["success"] = True
            return result

        result["success"] = True
        return result
    except Exception as e:
        result["error"] = str(e)

        try:
            if dst.exists() and dst.stat().st_size == 0:
                dst.unlink(missing_ok=True)
        except Exception:
            pass
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast parallel zstd compressor for a directory.")
    parser.add_argument("--level", type=int, default=3, help="zstd compression level (lower = faster, default 3).")
    parser.add_argument(
        "--workers", type=int, default=0, help="number of parallel worker threads (default auto based on CPU)."
    )
    parser.add_argument(
        "--format",
        type=str,
        default="tar",
        choices=("tar", "zip"),
        help="archive format for directories (default: tar)",
    )
    parser.add_argument("path", nargs="?", default=".", help="target directory (default: current)")
    args = parser.parse_args()

    target = Path(args.path).resolve()
    if not target.is_dir():
        print("Target must be a directory", file=sys.stderr)
        return 2

    cpu = os.cpu_count() or 1
    workers = args.workers if args.workers > 0 else min(32, cpu * 2)
    zstd_threads = max(1, min(4, cpu))

    before_total = gsz(target)

    dirs = list_dirs(target)
    if dirs:
        for d in dirs:
            base = str(d.parent / d.name)
            ok, info = compress_folder_sync(d, base, fmt=args.format)
            if ok:
                print(f"compressed {d.relative_to(target)} -> {Path(base + '.' + args.format).name}")
                try:
                    shutil.rmtree(d)
                except Exception as e:
                    print(f"warning: failed to remove {d}: {e}")
            else:
                print(f"failed to compress directory {d}: {info}")

    files = list_files(target)
    if not files:
        print("No files to compress")
        return 0

    total_original = 0
    total_compressed = 0
    successful = 0
    total_files = len(files)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(compress_file_sync, path, args.level, zstd_threads): path for path in files}

        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            path = futures[fut]
            print(f"\n[{i}/{total_files}] {path.name}")
            res = fut.result()
            before = res.get("before", 0) or (path.stat().st_size if path.exists() else 0)
            total_original += before
            if res["skipped"]:
                print(f"skipped {path.name}")
                continue
            if res["success"]:
                successful += 1
                after = res.get("after", 0)
                total_compressed += after
                reduction = 0.0
                if before:
                    reduction = (before - after) / before * 100
                print(f"{path.name} | {human_size(before)} → {human_size(after)} ({reduction:.2f}%)")
            else:
                print(f"Compression failed for {path}: {res.get('error')}")

    if total_original > 0 and successful > 0:
        savings = total_original - total_compressed
        savings_percent = (savings / total_original) * 100
        print(f"\nSpace saved: {human_size(savings)} ({savings_percent:.1f}%)")

    after_total = gsz(target)
    dsz = abs(before_total - after_total)
    ratio = (dsz / before_total * 100) if before_total else 0.0
    cprint(f"space saved: {human_size(dsz)} | {ratio:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
