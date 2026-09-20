from __future__ import annotations

import re
import shutil
import zipfile
from email.parser import HeaderParser
from pathlib import Path


def extract_metadata_from_wheel(wheel_path: Path) -> dict[str, str] | None:
    try:
        with zipfile.ZipFile(wheel_path, "r") as zf:
            metadata_files = [f for f in zf.namelist() if f.endswith(".dist-info/METADATA")]
            if not metadata_files:
                print(f"  Warning: No METADATA file found in {wheel_path.name}")
                return None
            with zf.open(metadata_files[0]) as f:
                content = f.read().decode("utf-8", errors="ignore")
            parser = HeaderParser()
            msg = parser.parsestr(content)
            name = msg.get("Name")
            version = msg.get("Version")
            if name and version:
                return {"name": name, "version": version}
            else:
                print(f"  Warning: Could not find Name/Version in METADATA of {wheel_path.name}")
                return None
    except zipfile.BadZipFile:
        print(f"  Error: {wheel_path.name} is not a valid zip file")
        return None
    except Exception as e:
        print(f"  Error reading {wheel_path.name}: {e}")
        return None


def extract_wheel_tags(filename: str) -> tuple[str, str, str] | None:
    patterns = [
        ".*?-.*?-.*?-(py3|py2\\.py3|py2|cp[0-9]+)-(none|abi[0-9]+|cp[0-9]+m?)-(manylinux[0-9_]+|linux|win_amd64|win32|macosx[0-9_]+)\\.whl$",
        ".*?-.*?-.*?-([a-z0-9]+(?:[\\.\\-][a-z0-9]+)?)-([a-z0-9]+(?:[\\.\\-][a-z0-9]+)?)-([a-z0-9_]+(?:[\\.\\-][a-z0-9_]+)?)\\.whl$",
    ]
    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            return match.group(1), match.group(2), match.group(3)
    if "cp3" in filename:
        py_match = re.search(r"cp3[0-9]", filename)
        if py_match:
            return py_match.group(0), "none", "any"
    return None


def reconstruct_wheel_name(wheel_path: Path, metadata: dict[str, str], original_filename: str) -> str | None:
    name = metadata["name"]
    version = metadata["version"]
    tags = extract_wheel_tags(wheel_path.name)
    if tags:
        python_tag, abi_tag, platform_tag = tags
        return f"{name}-{version}-{python_tag}-{abi_tag}-{platform_tag}.whl"
    else:
        with zipfile.ZipFile(wheel_path, "r") as zf:
            wheel_files = [f for f in zf.namelist() if f.endswith(".dist-info/WHEEL")]
            if wheel_files:
                with zf.open(wheel_files[0]) as f:
                    content = f.read().decode("utf-8", errors="ignore")
                    for line in content.split("\n"):
                        if line.startswith("Root-Is-Purelib: true"):
                            platform_tag = "any"
                            py_match = re.search(r"Tag: (.*?)-(.*?)-", content)
                            if py_match:
                                python_tag = py_match.group(1)
                                abi_tag = py_match.group(2) if len(py_match.groups()) > 1 else "none"
                                return f"{name}-{version}-{python_tag}-{abi_tag}-{platform_tag}.whl"
        print(f"  Warning: Could not determine tags for {wheel_path.name}, using generic 'py3-none-any'")
        return f"{name}-{version}-py3-none-any.whl"


def fix_whl_files_by_metadata(directory: str = ".", dry_run: bool = True, backup: bool = True):
    path = Path(directory)
    whl_files = list(path.glob("*.whl"))
    if not whl_files:
        print(f"No .whl files found in {directory}")
        return
    print(f"Found {len(whl_files)} .whl files")
    print("-" * 40)
    renamed_count = 0
    failed_files = []
    backup_dir = None
    if backup and not dry_run:
        backup_dir = path / "whl_backup"
        backup_dir.mkdir(exist_ok=True)
        print(f"Backups will be saved to: {backup_dir}")
    for idx, file_path in enumerate(whl_files, 1):
        print(f"\n[{idx}/{len(whl_files)}] Processing: {file_path.name}")
        metadata = extract_metadata_from_wheel(file_path)
        if not metadata:
            failed_files.append(file_path.name)
            continue
        proper_name = reconstruct_wheel_name(file_path, metadata, file_path.name)
        if not proper_name:
            failed_files.append(file_path.name)
            continue
        if proper_name != file_path.name:
            new_path = file_path.parent / proper_name
            if dry_run:
                print(f"  Would rename to: {proper_name}")
            else:
                if backup_dir:
                    backup_path = backup_dir / file_path.name
                    shutil.copy2(file_path, backup_path)
                    print(f"  Backup created: {backup_path.name}")
                try:
                    file_path.rename(new_path)
                    print(f"  ✓ Renamed to: {proper_name}")
                    renamed_count += 1
                except Exception as e:
                    print(f"  ✗ Error renaming: {e}")
                    failed_files.append(file_path.name)
        else:
            print(f"  Already has correct name: {file_path.name}")
    print("\n" + "=" * 40)
    print("SUMMARY:")
    print(f"  Total files: {len(whl_files)}")
    if not dry_run:
        print(f"  Successfully renamed: {renamed_count}")
        print(f"  Failed: {len(failed_files)}")
        if failed_files:
            print(f"  Failed files: {', '.join(failed_files)}")
    else:
        print(f"  Would rename: {renamed_count} files")
        print(f"  Would skip/error: {len(failed_files)}")
    if dry_run and renamed_count > 0:
        print("\n✓ Dry run complete. Run with --execute to apply changes.")
    return renamed_count, failed_files


def batch_fix_with_parallel(directory: str = ".", max_workers: int = 4) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    path = Path(directory)
    whl_files = list(path.glob("*.whl"))
    if not whl_files:
        print(f"No .whl files found in {directory}")
        return
    print(f"Processing {len(whl_files)} files with {max_workers} workers...")
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(extract_metadata_from_wheel, f): f for f in whl_files}
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                metadata = future.result()
                if metadata:
                    proper_name = reconstruct_wheel_name(file_path, metadata, file_path.name)
                    results[file_path.name] = metadata, proper_name
            except Exception as e:
                print(f"Error processing {file_path.name}: {e}")
    print("\nExtracted information:")
    for old_name, (metadata, proper_name) in results.items():
        print(f"  {old_name} -> {metadata['name']} {metadata['version']} -> {proper_name}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Fix batch-renamed .whl files by reading METADATA from inside each wheel",
        epilog="This is the most accurate method as it extracts the real package name and version.",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory containing .whl files (default: current directory)",
    )
    parser.add_argument(
        "--execute",
        "-e",
        action="store_true",
        help="Actually rename files (dry run by default)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating backups (backups are created by default)",
    )
    parser.add_argument(
        "--parallel",
        "-p",
        type=int,
        metavar="N",
        help="Use parallel processing with N workers (only for info extraction)",
    )
    parser.add_argument(
        "--info-only",
        "-i",
        action="store_true",
        help="Only show extracted info without renaming",
    )
    args = parser.parse_args()
    if args.info_only:
        print("Extracting wheel information (no renaming):")
        print("-" * 40)
        if args.parallel:
            batch_fix_with_parallel(args.directory, args.parallel)
        else:
            path = Path(args.directory)
            for whl_file in path.glob("*.whl"):
                metadata = extract_metadata_from_wheel(whl_file)
                if metadata:
                    proper_name = reconstruct_wheel_name(whl_file, metadata, whl_file.name)
                    print(f"\nFile: {whl_file.name}")
                    print(f"  Package: {metadata['name']}")
                    print(f"  Version: {metadata['version']}")
                    print(f"  Should be: {proper_name}")
    else:
        fix_whl_files_by_metadata(
            directory=args.directory,
            dry_run=not args.execute,
            backup=not args.no_backup,
        )


if __name__ == "__main__":
    raise SystemExit(main())
