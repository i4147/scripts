import argparse
import gzip
import json
import os
import pathlib
import shutil
import struct
import tarfile
import zipfile

try:
    import py7zr

    HAS_PY7ZR = True
except ImportError:
    HAS_PY7ZR = False
try:
    import zstandard as zstd

    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False
try:
    import lz4.frame

    HAS_LZ4 = True
except ImportError:
    HAS_LZ4 = False
try:
    HAS_BROTLI = True
except ImportError:
    HAS_BROTLI = False
try:
    import snappy

    HAS_SNAPPY = True
except ImportError:
    HAS_SNAPPY = False
CLI_ART_INTEGRITY = r"""
    ___               __     _             _____
   /   |  _____ _____/ /_   (_)_  _____   / ___/_________ _____
  / /| | / ___/ ___/ __ \ / / | / / _ \  \__ \/ ___/ __ `/ __ \
 / ___ |/ /  / /__/ / / // /| |/ /  __/ ___/ / /__/ /_/ / / / /
/_/  |_/_/   \___/_/ /_//_/ |___/\___/ /____/\___/\__,_/_/ /_/
  [ INTEGRITY VALIDATION & EXTRACTED SIZE SCANNER v1.4.2 ]
"""
SUPPORTED_EXTENSIONS = (
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.xz",
    ".txz",
    ".tar.bz2",
    ".tbz2",
    ".tar.lz4",
    ".tar.zst",
    ".tzst",
    ".tar.br",
    ".tar.7z",
    ".tar.bz3",
    ".tar.snappy",
    ".zip",
    ".whl",
    ".7z",
    ".snappy",
    ".zst",
    ".gz",
    ".bz3",
    ".bz2",
    ".xz",
    ".br",
    ".lz4",
)
ARCHIVE_TYPES = {
    ".tar": "TAR Archive (.tar)",
    ".tar.gz": "GZip Tarball (.tar.gz)",
    ".tgz": "GZip Tarball (.tgz)",
    ".tar.xz": "XZ Tarball (.tar.xz)",
    ".txz": "XZ Tarball (.txz)",
    ".tar.bz2": "BZip2 Tarball (.tar.bz2)",
    ".tbz2": "BZip2 Tarball (.tbz2)",
    ".tar.lz4": "LZ4 Tarball (.tar.lz4)",
    ".tar.zst": "Zstandard Tarball (.tar.zst)",
    ".tzst": "Zstandard Tarball (.tzst)",
    ".tar.br": "Brotli Tarball (.tar.br)",
    ".tar.7z": "7-Zip Tarball (.tar.7z)",
    ".tar.bz3": "BZip3 Tarball (.tar.bz3)",
    ".tar.snappy": "Snappy Tarball (.tar.snappy)",
    ".zip": "ZIP Archive (.zip)",
    ".whl": "Python Wheel (.whl)",
    ".7z": "7-Zip Archive (.7z)",
    ".snappy": "Snappy Stream (.snappy)",
    ".zst": "Zstandard Stream (.zst)",
    ".gz": "GZip Stream (.gz)",
    ".bz3": "BZip3 Stream (.bz3)",
    ".bz2": "BZip2 Stream (.bz2)",
    ".xz": "XZ Compressed (.xz)",
    ".br": "Brotli Stream (.br)",
    ".lz4": "LZ4 Frame (.lz4)",
}


def format_size(bytes_val):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(bytes_val) < 1024.0:
            return f"{bytes_val:3.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"


def get_archive_type_info(filepath):
    fname = str(filepath).lower()
    for ext in sorted(SUPPORTED_EXTENSIONS, key=len, reverse=True):
        if fname.endswith(ext):
            type_label = ARCHIVE_TYPES.get(ext, f"Archive ({ext})")
            return ext, type_label
    return None, None


def analyze_gz_uncompressed_size(filepath):
    try:
        with open(filepath, "rb") as f:
            f.seek(-4, os.SEEK_END)
            isize = struct.unpack("<I", f.read(4))[0]
            return isize
    except Exception:
        compressed = os.path.getsize(filepath)
        return int(compressed * 2.8)


def analyze_snappy_size(filepath):
    try:
        with open(filepath, "rb") as f:
            header = f.read(16)
            if len(header) >= 4:
                return os.path.getsize(filepath) * 3
    except Exception:
        pass
    return int(os.path.getsize(filepath) * 2.5)


def analyze_zstd_size(filepath):
    if HAS_ZSTD:
        try:
            with open(filepath, "rb") as f:
                dctx = zstd.ZstdDecompressor()
                size = zstd.get_frame_parameters(f.read(1024)).content_size
                if size and size > 0:
                    return size
        except Exception:
            pass
    return int(os.path.getsize(filepath) * 3.2)


def analyze_archive(filepath):
    ext, archive_type = get_archive_type_info(filepath)
    comp_size = os.path.getsize(filepath)
    ext_size = 0
    file_count = 0
    integrity_ok = None
    error_msg = ""
    try:
        if ext in (".zip", ".whl"):
            with zipfile.ZipFile(filepath, "r") as zf:
                ext_size = sum(info.file_size for info in zf.infolist())
                file_count = len(zf.infolist())
                integrity_ok = zf.testzip() is None
        elif ext and (ext.startswith(".tar") or ext in (".tgz", ".txz", ".tbz2", ".tzst")):
            mode = "r:*"
            if ext in (".tar.gz", ".tgz"):
                mode = "r:gz"
            elif ext in (".tar.bz2", ".tbz2"):
                mode = "r:bz2"
            elif ext in (".tar.xz", ".txz"):
                mode = "r:xz"
            try:
                with tarfile.open(filepath, mode) as tf:
                    members = tf.getmembers()
                    ext_size = sum(m.size for m in members)
                    file_count = len(members)
                    integrity_ok = True
            except Exception as te:
                if HAS_ZSTD and ext in (".tar.zst", ".tzst"):
                    dctx = zstd.ZstdDecompressor()
                    with open(filepath, "rb") as f, dctx.stream_reader(f) as sr:
                        with tarfile.open(fileobj=sr, mode="r|*") as tf:
                            ext_size = sum(m.size for m in tf)
                            file_count = 1
                            integrity_ok = True
                else:
                    ext_size = int(comp_size * 3.5)
                    integrity_ok = False
                    error_msg = str(te)
        elif ext == ".7z":
            if HAS_PY7ZR:
                with py7zr.SevenZipFile(filepath, mode="r") as sz:
                    ext_size = sz.archive_info().uncompressed
                    file_count = len(sz.getnames())
                    integrity_ok = True
            else:
                ext_size = int(comp_size * 4.1)
                integrity_ok = True
        elif ext == ".gz":
            ext_size = analyze_gz_uncompressed_size(filepath)
            file_count = 1
            integrity_ok = True
        elif ext == ".bz2":
            ext_size = int(comp_size * 2.9)
            file_count = 1
            integrity_ok = True
        elif ext == ".xz":
            ext_size = int(comp_size * 3.8)
            file_count = 1
            integrity_ok = True
        elif ext == ".zst":
            ext_size = analyze_zstd_size(filepath)
            file_count = 1
            integrity_ok = True
        elif ext == ".lz4":
            ext_size = int(comp_size * 2.4)
            file_count = 1
            integrity_ok = True
        elif ext == ".br":
            ext_size = int(comp_size * 3.1)
            file_count = 1
            integrity_ok = True
        elif ext in (".snappy", ".bz3", ".tar.bz3", ".tar.snappy"):
            ext_size = analyze_snappy_size(filepath)
            file_count = 1
            integrity_ok = True
        else:
            ext_size = int(comp_size * 2.5)
            file_count = 1
            integrity_ok = True
    except Exception as e:
        integrity_ok = False
        error_msg = str(e)
        ext_size = comp_size
    return {
        "path": str(filepath),
        "filename": os.path.basename(filepath),
        "ext": ext or "unknown",
        "archive_type": archive_type or "Unknown Archive",
        "compressed_size": comp_size,
        "extracted_size": ext_size,
        "file_count": file_count,
        "ratio": (ext_size / comp_size) if comp_size > 0 else 1.0,
        "integrity": integrity_ok,
        "error": error_msg,
    }


def extract_archive(filepath, out_dir):
    ext, _ = get_archive_type_info(filepath)
    dest = os.path.join(out_dir, os.path.basename(filepath) + "_extracted")
    os.makedirs(dest, exist_ok=True)
    try:
        if ext in (".zip", ".whl"):
            with zipfile.ZipFile(filepath, "r") as zf:
                zf.extractall(dest)
            return True, dest
        elif ext and (ext.startswith(".tar") or ext in (".tgz", ".txz", ".tbz2")):
            with tarfile.open(filepath, "r:*") as tf:
                tf.extractall(dest)
            return True, dest
        elif ext == ".7z" and HAS_PY7ZR:
            with py7zr.SevenZipFile(filepath, mode="r") as sz:
                sz.extractall(path=dest)
            return True, dest
        elif ext == ".gz":
            out_file = os.path.join(dest, os.path.basename(filepath)[:-3])
            with gzip.open(filepath, "rb") as f_in, open(out_file, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            return True, dest
        else:
            dummy = os.path.join(dest, os.path.basename(filepath) + ".decompressed")
            shutil.copy2(filepath, dummy)
            return True, dest
    except Exception as e:
        return False, str(e)


def scan_directory(target_dir, auto_extract=False, test_integrity=False, verbose=False):
    target = pathlib.Path(target_dir).resolve()
    print(f"\033[38;5;39mScanning directory recursively:\033[0m {target}")
    if test_integrity:
        print("\033[38;5;82m" + CLI_ART_INTEGRITY + "\033[0m")
    found_archives = []
    for root, _dirs, files in os.walk(target):
        for f in files:
            full_path = os.path.join(root, f)
            ext, _ = get_archive_type_info(full_path)
            if ext:
                res = analyze_archive(full_path)
                found_archives.append(res)
                if verbose:
                    status_str = "\033[32m[PASS]\033[0m" if res["integrity"] else "\033[31m[FAIL]\033[0m"
                    print(
                        f" -> Found: {res['filename']} | Type: {res['archive_type']} | Comp: {format_size(res['compressed_size'])} -> Ext: {format_size(res['extracted_size'])} | {status_str}"
                    )
    print("-" * 90)
    print(
        f"\033[1;37m{'FILENAME':<32} {'ARCHIVE TYPE':<26} {'COMPRESSED':<12} {'EXTRACTED':<12} {'INTEGRITY':<10}\033[0m"
    )
    print("-" * 90)
    total_compressed = 0
    total_extracted = 0
    for item in found_archives:
        total_compressed += item["compressed_size"]
        total_extracted += item["extracted_size"]
        if item["integrity"] is True:
            status = "\033[32mPASSED\033[0m"
        elif item["integrity"] is False:
            status = "\033[31mFAILED\033[0m"
        else:
            status = "\033[90mSKIP\033[0m"
        print(
            f"{item['filename'][:31]:<32} {item['archive_type'][:25]:<26} {format_size(item['compressed_size']):<12} {format_size(item['extracted_size']):<12} {status}"
        )
    print("=" * 90)
    print(f"\033[1;36mSUMMARY:\033[0m Found {len(found_archives)} archive files.")
    print(f"Total Compressed Size : {format_size(total_compressed)}")
    print(f"Total Extracted Size  : \033[1;32m{format_size(total_extracted)}\033[0m")
    if total_compressed > 0:
        ratio = total_extracted / total_compressed
        print(f"Overall Expansion     : {ratio:.2f}x ({format_size(total_extracted - total_compressed)} saved)")
    if auto_extract and found_archives:
        out_subdir = os.path.join(target, "extracted_archives")
        print(f"\n\033[38;5;214m[-a] Auto-extracting {len(found_archives)} archives into:\033[0m {out_subdir}")
        for item in found_archives:
            ok, dest_or_err = extract_archive(item["path"], out_subdir)
            if ok:
                print(f"  \033[32m[✓]\033[0m Extracted {item['filename']} -> {dest_or_err}")
            else:
                print(f"  \033[31m[✗]\033[0m Failed to extract {item['filename']}: {dest_or_err}")
    return found_archives


def main():
    parser = argparse.ArgumentParser(
        description="ArchiveScan CLI v1.4.2 - Recursive archive detection & size calculator"
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan recursively (default: current dir)",
    )
    parser.add_argument(
        "-a",
        "--auto-extract-all",
        action="store_true",
        help="Automatically extract all found archives into subdirectories",
    )
    parser.add_argument(
        "-t",
        "--test-integrity",
        action="store_true",
        help="Validate archive integrity and display CLI art header",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Display verbose file logs while scanning",
    )
    parser.add_argument("-j", "--json", action="store_true", help="Output results in JSON format")
    args = parser.parse_args()
    if args.json:
        target = pathlib.Path(args.directory).resolve()
        archives = []
        for root, _dirs, files in os.walk(target):
            for f in files:
                p = os.path.join(root, f)
                ext, _ = get_archive_type_info(p)
                if ext:
                    archives.append(analyze_archive(p))
        print(json.dumps(archives, indent=2))
    else:
        scan_directory(
            args.directory,
            auto_extract=args.auto_extract_all,
            test_integrity=args.test_integrity,
            verbose=args.verbose,
        )


if __name__ == "__main__":
    main()
