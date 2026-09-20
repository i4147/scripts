import hashlib
import json
import sys
from pathlib import Path

import brotlicffi
from dh import get_size
from termcolor import cprint

CHUNK_SIZE = 32 * 1024 * 1024
N_JOBS = -1


def calculate_sha256(filepath) -> str:
    sha256_hash = hashlib.sha256()
    with Path(filepath).open("rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def parallel_decompress(in_path: Path, out_path) -> bool:
    with out_path.open("wb", buffering=1024 * 1024) as fout:
        with in_path.open("rb") as fin:
            while True:
                size_bytes = fin.read(4)
                if not size_bytes:
                    break
                block_size = int.from_bytes(size_bytes, "big")
                block = fin.read(block_size)
                try:
                    decompressed_block = brotlicffi.decompress(block)
                    fout.write(decompressed_block)
                except brotlicffi.Error as e:
                    cprint(f"Brotli decompression error: {e}", "red")
                    return False
    return True


def process_decompress_file(br_fp) -> bool | None:
    br_fp = Path(br_fp)
    if not br_fp.exists() or br_fp.suffix != ".br":
        cprint(f"Skipping non-.br file: {br_fp}", "yellow")
        return None
    metadata_fp = Path(str(br_fp) + ".meta.json")
    if not metadata_fp.exists():
        cprint(
            f"Metadata file not found for {br_fp.name}. Cannot perform integrity check.",
            "red",
        )
        return False
    try:
        with Path(metadata_fp).open(encoding="utf-8") as mf:
            metadata = json.load(mf)
    except json.JSONDecodeError:
        cprint(f"Error decoding JSON from {metadata_fp.name}. Invalid metadata.", "red")
        return False
    except Exception as e:
        cprint(f"Error reading metadata file {metadata_fp.name}: {e}", "red")
        return False
    original_filename = metadata.get("original_filename", br_fp.stem)
    decompressed_path = br_fp.parent / original_filename
    expected_original_size = metadata.get("original_size")
    expected_original_hash = metadata.get("original_hash")
    if expected_original_size is None or expected_original_hash is None:
        cprint(
            f"Metadata in {metadata_fp.name} is incomplete (missing size or hash). Cannot perform integrity check.",
            "red",
        )
        return False
    cprint(f"Decompressing {br_fp.name} to {decompressed_path.name}...", "blue")
    if not parallel_decompress(br_fp, decompressed_path):
        cprint(f"Decompression failed for {br_fp.name}.", "red")
        if decompressed_path.exists():
            decompressed_path.unlink()
        return False
    actual_size = get_size(decompressed_path)
    actual_hash = calculate_sha256(decompressed_path)
    integrity_ok = True
    if actual_size != expected_original_size:
        cprint(
            f"Integrity check FAILED for {decompressed_path.name}: Size mismatch!",
            "red",
        )
        cprint(
            f"  Expected: {expected_original_size} bytes, Actual: {actual_size} bytes",
            "red",
        )
        integrity_ok = False
    if actual_hash != expected_original_hash:
        cprint(
            f"Integrity check FAILED for {decompressed_path.name}: Hash mismatch!",
            "red",
        )
        cprint(f"  Expected: {expected_original_hash}", "red")
        cprint(f"  Actual:   {actual_hash}", "red")
        integrity_ok = False
    if integrity_ok:
        cprint(f"Integrity check PASSED for {decompressed_path.name}.", "green")
        try:
            metadata_fp.unlink()
            br_fp.unlink()
            cprint(
                f"Removed metadata and compressed file: {metadata_fp.name}, {br_fp.name}",
                "cyan",
            )
        except Exception as e:
            cprint(f"Error removing auxiliary files: {e}", "red")
        return True
    else:
        cprint(
            f"Integrity check failed for {decompressed_path.name}. Keeping original compressed file and metadata.",
            "yellow",
        )
        return False


def main() -> None:
    root_dir = Path.cwd()
    args = sys.argv[1:]
    files_to_process = []
    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file() and p.suffix == ".br":
                files_to_process.append(p)
            elif p.is_dir():
                files_to_process.extend(list(p.glob("*.br")))
    else:
        files_to_process = list(root_dir.glob("*.br"))
    if not files_to_process:
        cprint("No .br files found to decompress.", "yellow")
        return
    success_count = 0
    fail_count = 0
    for br_file in files_to_process:
        if process_decompress_file(br_file):
            success_count += 1
        else:
            fail_count += 1
    cprint(
        f"\nDecompression summary: {success_count} successful, {fail_count} failed.",
        "blue",
    )


if __name__ == "__main__":
    sys.exit(main())
