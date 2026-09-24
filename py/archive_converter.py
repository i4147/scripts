import argparse
import bz2
import contextlib
import gzip
import io
import lzma
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Iterable, Iterator
from multiprocessing import Pool
from pathlib import Path
from typing import (
    BinaryIO,
    Final,
    List,
    Optional,
    Tuple,
)
import brotli
import cramjam
import lz4.frame
import py7zr
import zstandard as zstd
from loguru import logger

POOL_SIZE = 8
TAR_FAMILY = frozenset(
    {
        ".tar",
        ".tar.gz",
        ".tar.bz2",
        ".tar.xz",
        ".tar.zst",
        ".tar.br",
        ".tar.lz4",
        ".tar.7z",
        ".tar.sz",
    }
)
ZIP_FAMILY = frozenset({".zip", ".whl"})
INPUT_EXTS = tuple(sorted(TAR_FAMILY | ZIP_FAMILY, key=len, reverse=True))
ALLOWED_TO_FORMATS = frozenset(
    {
        ".tar.gz",
        ".tar.bz2",
        ".tar.xz",
        ".tar.zst",
        ".tar.br",
        ".tar.lz4",
        ".tar.7z",
        ".tar.sz",
        ".zip",
        ".whl",
    }
)
Entry = tuple[str, bytes]
ConvertArgs = tuple[str, str]
ConvertResult = tuple[str, int, bool, str]


def detect_ext(path):
    name = path.name.lower()
    for suffix in INPUT_EXTS:
        if name.endswith(suffix):
            return suffix
    return None


@contextlib.contextmanager
def _open_tar_input(path, ext):
    if ext == ".tar":
        with path.open("rb") as f:
            yield f
    elif ext == ".tar.gz":
        with gzip.open(path, "rb") as f:
            yield f
    elif ext == ".tar.bz2":
        with bz2.open(path, "rb") as f:
            yield f
    elif ext == ".tar.xz":
        with lzma.open(path, "rb") as f:
            yield f
    elif ext == ".tar.zst":
        with path.open("rb") as f_raw:
            dctx = zstd.ZstdDecompressor()
            with dctx.stream_reader(f_raw) as reader:
                yield reader
    elif ext == ".tar.lz4":
        with lz4.frame.open(path, "rb") as f:
            yield f
    elif ext == ".tar.br":
        data = brotli.decompress(path.read_bytes())
        yield io.BytesIO(data)
    elif ext == ".tar.sz":
        data = bytes(cramjam.snappy.decompress(path.read_bytes()))
        yield io.BytesIO(data)
    elif ext == ".tar.7z":
        with py7zr.SevenZipFile(str(path), mode="r") as archive:
            members = archive.readall()
            for bio in members.values():
                yield io.BytesIO(bio.read())
                return
        raise ValueError(f"empty 7z archive: {path}")
    else:
        raise ValueError(f"unsupported tar input extension: {ext}")


def iter_entries(path, ext):
    if ext in ZIP_FAMILY:
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                with zf.open(info) as f:
                    yield info.filename, f.read()
        return
    if ext in TAR_FAMILY:
        with (
            _open_tar_input(path, ext) as stream,
            tarfile.open(fileobj=stream, mode="r|") as tf,
        ):
            for member in tf:
                if not member.isfile():
                    continue
                fobj = tf.extractfile(member)
                if fobj is None:
                    continue
                yield member.name, fobj.read()
        return
    raise ValueError(f"unsupported input extension: {ext}")


def _add_tar_entries(tf, entries):
    total = 0
    for name, data in entries:
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
        total += len(data)
    return total


def _write_tar(entries, dst, ext):
    if ext == ".tar.gz":
        with gzip.open(dst, "wb") as f, tarfile.open(fileobj=f, mode="w|") as tf:
            return _add_tar_entries(tf, entries)
    if ext == ".tar.bz2":
        with bz2.open(dst, "wb") as f, tarfile.open(fileobj=f, mode="w|") as tf:
            return _add_tar_entries(tf, entries)
    if ext == ".tar.xz":
        with (
            lzma.open(dst, "wb", preset=9) as f,
            tarfile.open(fileobj=f, mode="w|") as tf,
        ):
            return _add_tar_entries(tf, entries)
    if ext == ".tar.zst":
        cctx = zstd.ZstdCompressor(level=9)
        with dst.open("wb") as f_raw, cctx.stream_writer(f_raw) as writer:
            with tarfile.open(fileobj=writer, mode="w|") as tf:
                return _add_tar_entries(tf, entries)
    if ext == ".tar.lz4":
        with lz4.frame.open(dst, "wb") as f, tarfile.open(fileobj=f, mode="w|") as tf:
            return _add_tar_entries(tf, entries)
    if ext == ".tar.br":
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w|") as tf:
            total = _add_tar_entries(tf, entries)
        dst.write_bytes(brotli.compress(buf.getvalue(), quality=11))
        return total
    if ext == ".tar.sz":
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w|") as tf:
            total = _add_tar_entries(tf, entries)
        dst.write_bytes(bytes(cramjam.snappy.compress(buf.getvalue())))
        return total
    if ext == ".tar.7z":
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            with tmp_path.open("wb") as f, tarfile.open(fileobj=f, mode="w|") as tf:
                total = _add_tar_entries(tf, entries)
            with py7zr.SevenZipFile(str(dst), mode="w") as archive:
                archive.write(str(tmp_path), arcname="archive.tar")
            return total
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
    raise ValueError(f"unsupported tar output extension: {ext}")


def write_entries(entries, dst, ext):
    if ext in ZIP_FAMILY:
        total = 0
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in entries:
                zf.writestr(name, data)
                total += len(data)
        return total
    if ext in TAR_FAMILY:
        return _write_tar(entries, dst, ext)
    raise ValueError(f"unsupported output extension: {ext}")


def convert_one(args):
    src_str, target_ext = args
    src = Path(src_str)
    input_ext = detect_ext(src)
    if input_ext is None:
        return (src_str, 0, False, f"unsupported input format: {src.name}")
    stem = src.name
    for suffix in INPUT_EXTS:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    dst = src.with_name(stem + target_ext)
    if dst == src:
        return (src_str, 0, True, f"skipped (already {target_ext}): {src.name}")
    if dst.exists():
        return (src_str, 0, True, f"skipped (exists): {dst.name}")
    try:
        src_size = src.stat().st_size
        write_entries(iter_entries(src, input_ext), dst, target_ext)
        dst_size = dst.stat().st_size
        src.unlink()
        delta = dst_size - src_size
        return (
            src_str,
            delta,
            True,
            f"converted -> {dst.name}, removed original",
        )
    except Exception as exc:
        try:
            if dst.exists():
                dst.unlink()
        except Exception:
            pass
        return (src_str, 0, False, f"error: {exc}")


def _collect_inputs(args):
    candidates = []
    if not args:
        candidates.extend(Path.cwd().iterdir())
    else:
        for arg in args:
            p = Path(arg)
            if p.is_dir():
                candidates.extend(p.iterdir())
            else:
                candidates.append(p)
    files = []
    for p in candidates:
        if not p.is_file():
            continue
        if detect_ext(p) is None:
            logger.warning("Skipping unsupported file: {}", p.name)
            continue
        files.append(p)
    return files


def format_size(num_bytes):
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} PB"


def _build_parser():
    parser = argparse.ArgumentParser(description=("Convert archives between tar-compressed and zip-based formats."))
    parser.add_argument(
        "inputs",
        nargs="*",
        help=("Input archive files or directories (default: current directory)"),
    )
    parser.add_argument(
        "-t",
        "--to",
        required=True,
        choices=sorted(ALLOWED_TO_FORMATS),
        help="Target archive format (e.g. .tar.xz or .zip)",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    target_ext = args.to
    files = _collect_inputs(list(args.inputs))
    if not files:
        logger.warning("No convertible archives found.")
        return 0
    logger.info("Found {} archive(s); converting to {}", len(files), target_ext)
    tasks = [(str(p), target_ext) for p in files]
    results = []
    with Pool(processes=POOL_SIZE) as pool:
        for result in pool.imap_unordered(convert_one, tasks):
            results.append(result)
    ok_count = sum(1 for _, _, ok, _ in results if ok)
    fail_count = len(results) - ok_count
    net_delta = sum(delta for _, delta, _, _ in results)
    logger.info(
        "Summary: total={} ok={} failed/skipped={}",
        len(files),
        ok_count,
        fail_count,
    )
    for src, delta, ok, msg in sorted(results, key=lambda x: x[0]):
        status = "OK" if ok else "FAIL"
        logger.info("[{}] {}: {}", status, Path(src).name, msg)
    if net_delta < 0:
        logger.info("Net space saved: {}", format_size(-net_delta))
    elif net_delta > 0:
        logger.info("Net extra used: {}", format_size(net_delta))
    else:
        logger.info("Net disk usage change: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
