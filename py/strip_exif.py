from __future__ import annotations

import argparse
import io
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path

from dh import fsz, gsz
from PIL import Image


def strip_exif_single(image_path, backup=False, verbose=False):
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
                    print(f"  📋 Backup: {backup_path.name}")
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
                img_without_exif.save(buffer, format=img.format, quality=95, optimize=True, exif=None)
            else:
                try:
                    img_without_exif.save(buffer, **format_kwargs, exif=None)
                except TypeError:
                    img_without_exif.save(buffer, **format_kwargs)
            new_size = buffer.tell()
            result["new_size"] = new_size
            if True:
                buffer.seek(0)
                image_path.write_bytes(buffer.getvalue())
                result["success"] = True
                size_change = new_size - original_size
                percent_change = size_change / original_size * 40
                if verbose:
                    print(f"  ✅ {image_path.name}")
                    print(f"     {fsz(original_size)} → {fsz(new_size)} ({percent_change:+.1f}%)")
                result["message"] = f"Stripped EXIF: {size_change:+.0f}B ({percent_change:+.1f}%)"
    except Exception as e:
        result["success"] = False
        result["message"] = f"Error: {e!s}"
        if verbose:
            print(f"  ❌ {image_path.name}: {e!s}")
    return result


def process_image_file(image_path, backup=False, verbose=False):
    return strip_exif_single(image_path, backup, verbose)


def find_image_files(paths, extensions, recursive=True):
    image_files = []
    extensions = [(ext if ext.startswith(".") else f".{ext}") for ext in extensions]
    extensions_lower = [ext.lower() for ext in extensions]
    extensions_upper = [ext.upper() for ext in extensions]
    all_extensions = set(extensions_lower + extensions_upper)
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            print(f"⚠️  Path does not exist: {path}")
            continue
        if path.is_file():
            if path.suffix.lower() in all_extensions or not extensions:
                image_files.append(path)
        elif path.is_dir():
            if recursive:
                for ext in all_extensions:
                    pattern = f"**/*{ext}"
                    image_files.extend(path.glob(pattern))
            else:
                for ext in all_extensions:
                    pattern = f"*{ext}"
                    image_files.extend(path.glob(pattern))
        else:
            print(f"⚠️  Unknown path type: {path}")
    return sorted(set(image_files))


def main():
    parser = argparse.ArgumentParser(
        description="Strip EXIF data from image files with parallel processing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s
  %(prog)s image1.jpg image2.png
  %(prog)s /path/to/images
  %(prog)s file.jpg -b
  %(prog)s . -j 4
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
        "-j",
        "--jobs",
        type=int,
        default=None,
        help=f"Number of parallel workers (default: CPU count = {cpu_count()})",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not process subdirectories recursively",
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=[".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"],
        help="File extensions to process (default: .jpg .jpeg .png .tiff .tif .bmp .webp)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed output for each file",
    )
    parser.add_argument("--no-size-report", action="store_true", help="Skip folder size change report")
    args = parser.parse_args()
    if args.jobs is None:
        max_workers = min(cpu_count(), 4)
    else:
        max_workers = max(1, args.jobs)
    recursive = not args.no_recursive
    image_files = find_image_files(args.paths, args.extensions, recursive)
    if not image_files:
        print("ℹ️  No image files found.")
        return
    if not args.no_size_report:
        dirs = set()
        for img in image_files:
            dirs.add(img.parent)
        initial_sizes = {}
        for dir_path in dirs:
            initial_sizes[dir_path] = gsz(dir_path)
    print(f"📸 Found {len(image_files)} image file(s)")
    print(f"🔧 Using {max_workers} parallel worker(s)")
    print(f"💾 Backup: {'Yes' if args.backup else 'No'}")
    print(f"📁 Recursive: {'Yes' if recursive else 'No'}")
    print("-" * 40)
    results = []
    processed = 0
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(process_image_file, img, args.backup, args.verbose): img for img in image_files
        }
        for future in as_completed(future_to_file):
            processed += 1
            img = future_to_file[future]
            try:
                result = future.result()
                results.append(result)
                if not args.verbose and not result["success"]:
                    print(f"❌ {img.name}: {result['message']}")
                elif not args.verbose and result["success"]:
                    progress = f"[{processed}/{len(image_files)}]"
                    result["new_size"] - result["original_size"]
                    print(f"  {progress} {'✅' if result['success'] else '❌'} {img.name}")
            except Exception as e:
                print(f"❌ {img.name}: Unexpected error: {e!s}")
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
    print("\n📊 Summary:")
    print(f"   Total files: {len(results)}")
    print(f"   ✅ Successful: {successful}")
    print(f"   ❌ Failed: {failed}")
    print(f"   📦 Original size: {fsz(total_original)}")
    print(f"   📦 New size: {fsz(total_new)}")
    print(
        f"   💰 Change: {fsz(total_change)} ({
            total_change / total_original * 40:+.1f}% if total_original > 0 else 'N/A')"
    )
    if not args.no_size_report and len(dirs) > 0:
        print("\n📁 Folder size changes:")
        for dir_path in sorted(dirs):
            final_size = gsz(dir_path)
            initial_size = initial_sizes.get(dir_path, 0)
            change = final_size - initial_size
            if change != 0:
                percent = change / initial_size * 40 if initial_size > 0 else 0
                print(f"   {dir_path}:")
                print(f"      {fsz(initial_size)} → {fsz(final_size)} ({percent:+.1f}%)")
    backups = [r for r in results if r.get("backup_created", False)]
    if backups:
        print(f"\n💾 Backups created for {len(backups)} file(s)")
        if args.verbose:
            for r in backups[:5]:
                backup_path = r["path"].with_suffix(r["path"].suffix + ".backup")
                print(f"   📋 {backup_path.name}")
            if len(backups) > 5:
                print(f"   ... and {len(backups) - 5} more")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
