import argparse
import io
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Any
from dh import fsz, gsz
from loguru import logger
from PIL import Image

DEFAULT_EXTENSIONS = [
    ".jpg",
    ".jpeg",
    ".png",
    ".tiff",
    ".tif",
    ".bmp",
    ".webp",
]
FIXED_WORKERS = 8


def strip_exif_single(
    image_path,
    backup=False,
    verbose=False,
):
    result = {
        "path": image_path,
        "success": False,
        "original_size": 0,
        "new_size": 0,
        "message": "",
        "backup_created": False,
    }
    try:
        original_size = image_path.stat().st_size
        result["original_size"] = original_size
        with Image.open(image_path) as img:
            if backup:
                backup_path = image_path.with_suffix(image_path.suffix + ".backup")
                backup_path.write_bytes(image_path.read_bytes())
                result["backup_created"] = True
                if verbose:
                    logger.debug(f"📋 Backup: {backup_path.name}")
            img_without_exif = Image.new(img.mode, img.size)
            img_without_exif.putdata(list(img.getdata()))
            buffer = io.BytesIO()
            format_kwargs = {"format": img.format}
            if img.format == "JPEG":
                format_kwargs["quality"] = 95
                format_kwargs["optimize"] = True
            elif img.format == "PNG":
                format_kwargs["optimize"] = True
            if img.format == "JPEG":
                img_without_exif.save(
                    buffer,
                    format=img.format,
                    quality=95,
                    optimize=True,
                    exif=None,
                )
            else:
                try:
                    img_without_exif.save(buffer, **format_kwargs, exif=None)
                except TypeError:
                    img_without_exif.save(buffer, **format_kwargs)
            new_size = buffer.tell()
            result["new_size"] = new_size
            buffer.seek(0)
            image_path.write_bytes(buffer.getvalue())
            result["success"] = True
            size_change = new_size - original_size
            percent_change = size_change / original_size * 100
            if verbose:
                print(f"✅ {image_path.name}")
                print(f"   {fsz(original_size)} → {fsz(new_size)} ({percent_change:+.1f}%)")
            result["message"] = f"Stripped EXIF: {size_change:+.0f}B ({percent_change:+.1f}%)"
    except Exception as e:
        result["success"] = False
        result["message"] = f"Error: {e!s}"
        if verbose:
            logger.error(f"❌ {image_path.name}: {e!s}")
    return result


def process_image_file(
    image_path,
    backup=False,
    verbose=False,
):
    return strip_exif_single(image_path, backup, verbose)


def find_image_files(
    paths,
    extensions,
    recursive=True,
):
    image_files = []
    normalized = [(ext if ext.startswith(".") else f".{ext}") for ext in extensions]
    all_extensions = set()
    for ext in normalized:
        all_extensions.add(ext.lower())
        all_extensions.add(ext.upper())
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            logger.warning(f"⚠️  Path does not exist: {path}")
            continue
        if path.is_file():
            if not all_extensions or path.suffix in all_extensions:
                image_files.append(path)
        elif path.is_dir():
            if recursive:
                for ext in all_extensions:
                    image_files.extend(path.glob(f"**/*{ext}"))
            else:
                for ext in all_extensions:
                    image_files.extend(path.glob(f"*{ext}"))
        else:
            logger.warning(f"⚠️  Unknown path type: {path}")
    return sorted(set(image_files))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Strip EXIF data from image files with parallel processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s image1.jpg image2.png
  %(prog)s /path/to/images
  %(prog)s file.jpg -b
  %(prog)s . --no-recursive
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-b",
        "--backup",
        action="store_true",
        help="Create backup files (.backup) before stripping EXIF",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not process subdirectories recursively",
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=DEFAULT_EXTENSIONS,
        help=("File extensions to process (default: .jpg .jpeg .png .tiff .tif .bmp .webp)"),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed output for each file",
    )
    parser.add_argument(
        "--no-size-report",
        action="store_true",
        help="Skip folder size change report",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    max_workers = FIXED_WORKERS
    logger.debug(f"Fixed worker count: {max_workers} (CPU count reported: {cpu_count()})")
    recursive = not args.no_recursive
    image_files = find_image_files(args.paths, args.extensions, recursive)
    if not image_files:
        print("ℹ️  No image files found.")
        return 0
    dirs = set()
    initial_sizes = {}
    if not args.no_size_report:
        for img in image_files:
            dirs.add(img.parent)
        for dir_path in dirs:
            initial_sizes[dir_path] = gsz(dir_path)
    print(f"📸 Found {len(image_files)} image file(s)")
    print(f"🔧 Using {max_workers} parallel worker(s)")
    print(f"💾 Backup: {'Yes' if args.backup else 'No'}")
    print(f"📁 Recursive: {'Yes' if recursive else 'No'}")
    print("-" * 40)
    results = []
    processed = 0
    with Pool(processes=max_workers) as pool:
        async_results = [
            (
                img,
                pool.apply_async(
                    process_image_file,
                    args=(img, args.backup, args.verbose),
                ),
            )
            for img in image_files
        ]
        for img, async_result in async_results:
            processed += 1
            try:
                result = async_result.get()
                results.append(result)
                if not args.verbose and not result["success"]:
                    logger.error(f"❌ {img.name}: {result['message']}")
                elif not args.verbose and result["success"]:
                    progress = f"[{processed}/{len(image_files)}]"
                    print(f"  {progress} ✅ {img.name}")
            except Exception as e:
                logger.error(f"❌ {img.name}: Unexpected error: {e!s}")
                results.append(
                    {
                        "path": img,
                        "success": False,
                        "original_size": 0,
                        "new_size": 0,
                        "message": f"Unexpected error: {e!s}",
                        "backup_created": False,
                    }
                )
    print("-" * 40)
    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful
    total_original = sum(r["original_size"] for r in results)
    total_new = sum(r["new_size"] for r in results)
    total_change = total_new - total_original
    print("📊 Summary:")
    print(f"   Total files: {len(results)}")
    print(f"   ✅ Successful: {successful}")
    print(f"   ❌ Failed: {failed}")
    print(f"   📦 Original size: {fsz(total_original)}")
    print(f"   📦 New size: {fsz(total_new)}")
    if total_original > 0:
        print(f"   💰 Change: {fsz(total_change)} ({total_change / total_original * 100:+.1f}%)")
    else:
        print(f"   💰 Change: {fsz(total_change)} (N/A)")
    if not args.no_size_report and len(dirs) > 0:
        print("📁 Folder size changes:")
        for dir_path in sorted(dirs):
            final_size = gsz(dir_path)
            initial_size = initial_sizes.get(dir_path, 0)
            change = final_size - initial_size
            if change != 0:
                percent = change / initial_size * 100 if initial_size > 0 else 0.0
                print(f"   {dir_path}:")
                print(f"      {fsz(initial_size)} → {fsz(final_size)} ({percent:+.1f}%)")
    backups = [r for r in results if r.get("backup_created", False)]
    if backups:
        print(f"💾 Backups created for {len(backups)} file(s)")
        if args.verbose:
            for r in backups[:5]:
                backup_path = r["path"].with_suffix(r["path"].suffix + ".backup")
                print(f"   📋 {backup_path.name}")
            if len(backups) > 5:
                print(f"   ... and {len(backups) - 5} more")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warning("⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)
