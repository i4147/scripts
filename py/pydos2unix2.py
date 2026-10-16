from argparse import Namespace
import argparse
import fnmatch
import logging
import mmap
from multiprocessing import Pool
from pathlib import Path


def is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
        if b"\x00" in chunk:
            return True
        text_chars = bytearray(range(32, 127)) + b"\n\r\t\b"
        nontext = sum(1 for b in chunk if b not in text_chars)
        return nontext / max(len(chunk), 1) > 0.30
    except Exception:
        return True


def needs_conversion(path: Path) -> bool:
    try:
        with (
            path.open("rb") as f,
            mmap.mmap(
                f.fileno(),
                0,
                access=mmap.ACCESS_READ,
            ) as mm,
        ):
            return mm.find(b"\r\n") != -1
    except Exception:
        return False


def convert_in_place(path: Path) -> None:
    with path.open("r+b") as f:
        try:
            with mmap.mmap(f.fileno(), 0) as mm:
                data = mm[:]
                new = data.replace(b"\r\n", b"\n")
                if new == data:
                    return
                mm.seek(0)
                mm.write(new)
                mm.flush()
                f.truncate(len(new))
        except Exception:
            raise


def convert_with_temp(path: Path) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with (
        path.open(
            "r",
            encoding="utf-8",
            errors="ignore",
            newline="",
        ) as src,
        tmp_path.open("w", encoding="utf-8", newline="") as dst,
    ):
        for line in src:
            dst.write(line.replace("\r\n", "\n"))
    Path(tmp_path).replace(path)


def safe_convert(path: Path, dry_run: bool = False) -> str:
    if not path.is_file():
        return f"SKIP (not file): {path}"
    if is_binary(path):
        return f"SKIP (binary): {path}"
    if not needs_conversion(path):
        return f"OK (already unix): {path}"
    if dry_run:
        return f"DRY-RUN (would convert): {path}"
    try:
        convert_in_place(path)
        return f"CONVERTED (mmap): {path}"
    except Exception:
        convert_with_temp(path)
        return f"CONVERTED (temp): {path}"


def scan_paths(inputs, recursive: bool, exclude_patterns) -> list[Path]:
    paths = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            if recursive:
                for f in p.rglob("*"):
                    paths.append(f)
            else:
                for f in p.glob("*"):
                    paths.append(f)
        else:
            paths.append(p)
    filtered = []
    for p in paths:
        name = str(p)
        if any(fnmatch.fnmatch(name, pat) for pat in exclude_patterns):
            continue
        filtered.append(p)
    return filtered


def worker(args) -> str:
    path, dry_run = args
    return safe_convert(path, dry_run=dry_run)


def parse_args() -> Namespace:
    parser = argparse.ArgumentParser(description="Fast dos2unix converter (mmap-optimized).")
    parser.add_argument(
        "paths",
        nargs="+",
        help="Files or directories to process.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Scan directories recursively.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not modify files.",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Parallel workers.",
    )
    parser.add_argument(
        "--chunksize",
        type=int,
        default=50,
        help="Chunk size for parallel map.",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Glob patterns to exclude.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=(logging.DEBUG if args.verbose else logging.INFO),
        format="%(message)s",
    )
    files = scan_paths(args.paths, args.recursive, args.exclude)
    tasks = [(p, args.dry_run) for p in files]
    if args.parallel > 1:
        with Pool(args.parallel) as pool:
            results = pool.imap_unordered(
                worker,
                tasks,
                chunksize=args.chunksize,
            )
            for res in results:
                logging.info(res)
    else:
        for p in files:
            res = safe_convert(p, dry_run=args.dry_run)
            logging.info(res)


if __name__ == "__main__":
    main()
