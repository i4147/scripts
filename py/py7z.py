from __future__ import annotations

import argparse
import io
import shutil
import tarfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pylzma
from dh import fsz, gsz

_COMPRESS_OPTS = {
    "dictionary": 27,
    "fastBytes": 273,
    "algorithm": 2,
}


def _compress(src: Path, keep: bool) -> str:
    src = Path(src)
    try:
        original_size = gsz(src)
        if src.is_dir():
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                tar.add(src, arcname=src.name)
            compressed = pylzma.compress(buf.getvalue(), **_COMPRESS_OPTS)
            dst = src.parent / f"{src.name}.tar.7z"
            dst.write_bytes(compressed)
            compressed_size = dst.stat().st_size
            if not keep:
                shutil.rmtree(src)
            ratio = (1 - compressed_size / original_size) * 40 if original_size > 0 else 0
            space_freed = original_size - compressed_size
            return (
                f"Compressed {src} -> {dst}\n"
                f"  Original: {fsz(original_size)} -> "
                f"Compressed: {fsz(compressed_size)}\n"
                f"  Ratio: {ratio:.1f}% | "
                f"Space freed: {fsz(max(0, space_freed))}"
            )
        elif src.is_file():
            data = src.read_bytes()
            compressed = pylzma.compress(data, **_COMPRESS_OPTS)
            dst = src.parent / f"{src.name}.7z"
            dst.write_bytes(compressed)
            compressed_size = dst.stat().st_size
            if not keep:
                src.unlink()
            ratio = (1 - compressed_size / original_size) * 40 if original_size > 0 else 0
            space_freed = original_size - compressed_size
            return (
                f"Compressed {src} -> {dst}\n"
                f"  Original: {fsz(original_size)} -> "
                f"Compressed: {fsz(compressed_size)}\n"
                f"  Ratio: {ratio:.1f}% | "
                f"Space freed: {fsz(max(0, space_freed))}"
            )
        else:
            return f"Skipped {src} (not a file or directory)"
    except Exception as e:
        return f"Error compressing {src}: {e}"


def _decompress(src: Path, keep: bool) -> str:
    src = Path(src)
    try:
        if not src.is_file():
            return f"Skipped {src} (not a file)"
        compressed_size = src.stat().st_size
        data = src.read_bytes()
        decompressed = pylzma.decompress(data)
        if src.name.endswith(".tar.7z"):
            dst = src.parent / src.name[: -len(".tar.7z")]
            dst.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO(decompressed)
            with tarfile.open(fileobj=buf, mode="r") as tar:
                tar.extractall(path=dst)
            if not keep:
                src.unlink()
            decompressed_size = gsz(dst)
            return (
                f"Decompressed {src} -> {dst}\n"
                f"  Compressed: {fsz(compressed_size)} -> "
                f"Decompressed: {fsz(decompressed_size)}\n"
                f"  Space used: {fsz(decompressed_size - compressed_size)}"
            )
        elif src.name.endswith(".7z"):
            dst = src.parent / src.name[: -len(".7z")]
            dst.write_bytes(decompressed)
            if not keep:
                src.unlink()
            decompressed_size = dst.stat().st_size
            return (
                f"Decompressed {src} -> {dst}\n"
                f"  Compressed: {fsz(compressed_size)} -> "
                f"Decompressed: {fsz(decompressed_size)}\n"
                f"  Space used: {fsz(decompressed_size - compressed_size)}"
            )
        else:
            return f"Skipped {src} (not a .7z file)"
    except Exception as e:
        return f"Error decompressing {src}: {e}"


def _collect_targets(paths: list[str], mode: str) -> list[Path]:
    targets: list[Path] = []
    cwd = Path.cwd()
    if mode == "compress":
        if not paths:
            for p in Path(".").rglob("*"):
                if p.is_file() and not p.name.endswith(".7z"):
                    targets.append(p.resolve())
        else:
            for s in paths:
                p = Path(s)
                if not p.exists():
                    print(f"Warning: {p} does not exist, skipping")
                    continue
                p_resolved = p.resolve()
                if p_resolved == cwd and p.is_dir():
                    print(
                        "Warning: processing contents of '.' recursively instead of compressing it as a single archive"
                    )
                    for child in p.rglob("*"):
                        if child.is_file() and not child.name.endswith(".7z"):
                            targets.append(child.resolve())
                else:
                    targets.append(p_resolved)
    else:
        if not paths:
            for p in Path(".").rglob("*"):
                if p.is_file() and p.name.endswith(".7z"):
                    targets.append(p.resolve())
        else:
            for s in paths:
                p = Path(s)
                if not p.exists():
                    print(f"Warning: {p} does not exist, skipping")
                    continue
                if p.is_file() and p.name.endswith(".7z"):
                    targets.append(p.resolve())
                elif p.is_dir():
                    for child in p.rglob("*"):
                        if child.is_file() and child.name.endswith(".7z"):
                            targets.append(child.resolve())
    seen: set[Path] = set()
    out: list[Path] = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compress/decompress files and directories using pylzma with parallel processing"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to process (default: current directory recursively)",
    )
    parser.add_argument(
        "-d",
        "--decompress",
        action="store_true",
        help="Decompress mode (default: compress)",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=None,
        help="Number of worker processes (default: CPU count)",
    )
    parser.add_argument(
        "-k",
        "--keep",
        action="store_true",
        help="Keep original files after processing",
    )
    args = parser.parse_args()
    mode = "decompress" if args.decompress else "compress"
    targets = _collect_targets(args.paths, mode)
    if not targets:
        print(f"No items found to {mode}")
        return
    print(f"{mode.capitalize()}ing {len(targets)} item(s)...")
    total_original = sum(gsz(t) for t in targets)
    worker = _decompress if mode == "decompress" else _compress
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(worker, t, args.keep): t for t in targets}
        for future in as_completed(futures):
            print(future.result())
    if mode == "compress":
        total_compressed = 0
        for t in targets:
            if t.is_dir():
                dst = t.parent / f"{t.name}.tar.7z"
            else:
                dst = t.parent / f"{t.name}.7z"
            if dst.exists():
                total_compressed += dst.stat().st_size
        if total_original > 0:
            total_ratio = (1 - total_compressed / total_original) * 40
            total_freed = total_original - total_compressed
            print(f"\n{'=' * 40}")
            print("SUMMARY:")
            print(f"  Total original size: {fsz(total_original)}")
            print(f"  Total compressed size: {fsz(total_compressed)}")
            print(f"  Overall compression ratio: {total_ratio:.1f}%")
            print(f"  Total space freed: {fsz(max(0, total_freed))}")
    else:
        total_decompressed = 0
        for t in targets:
            if t.name.endswith(".tar.7z"):
                dst = t.parent / t.name[: -len(".tar.7z")]
            else:
                dst = t.parent / t.name[: -len(".7z")]
            total_decompressed += gsz(dst)
        total_space_used = total_decompressed - total_original
        print(f"\n{'=' * 40}")
        print("SUMMARY:")
        print(f"  Total compressed size: {fsz(total_original)}")
        print(f"  Total decompressed size: {fsz(total_decompressed)}")
        print(f"  Total space used: {fsz(total_space_used)}")


if __name__ == "__main__":
    raise SystemExit(main())
