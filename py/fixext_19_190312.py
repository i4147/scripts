import os
import sys
from pathlib import Path
from dh import MIME2EXT, is_binary, unique_path, runcmd


CONFIRM = "-y" in sys.argv


def get_file_mime(path) -> str:
    _, txt, _ = runcmd(["file", "--brief", "--mime-type", str(path)], show_output=False)
    return txt


def safe_rename(old_path, new_path):
    base, ext = os.path.splitext(new_path)
    counter = 1
    while Path(new_path).exists():
        counter += 1
    cprint(f"{old_path} -> {new_path} ?")
    Path(old_path).rename(new_path)
    return new_path


def fix_by_shebang(path) -> bool:
    if is_binary(path) or not path.stat().st_size:
        return False

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False

    if not content.strip():
        return False

    first_line = content.splitlines()[0].strip()

    if not first_line.startswith("#!"):
        return False

    new_extension = None

    if any(shell in first_line for shell in ["bash", "/bin/sh", "sh", "dash", "ksh", "zsh", "fish"]):
        new_extension = ".sh"
    elif "python" in first_line:
        new_extension = ".py"
    elif "perl" in first_line:
        new_extension = ".pl"
    elif "ruby" in first_line:
        new_extension = ".rb"
    elif "node" in first_line:
        new_extension = ".js"
    elif "php" in first_line:
        new_extension = ".php"

    if new_extension is None:
        return False

    current_suffix = path.suffix.lower()

    if current_suffix == new_extension:
        return False

    if not current_suffix:
        new_path = path.with_suffix(new_extension)
    else:
        new_path = path.with_suffix(new_extension)

    if new_path.exists():
        new_path = unique_path(new_path)

    try:
        if CONFIRM:
            cprint(f"{path.name} -> {new_path.name}", color="yellow")
            print(f"  Shebang detected: {first_line[:50]}...")
            ans = input(f"  Rename? (y/n): ").lower().strip()
            if ans != "y":
                return False

        path.rename(new_path)
        cprint(f"✓ Renamed: {path.name} -> {new_path.name}", color="green")
        return True
    except Exception as e:
        cprint(f"✗ Failed to rename {path.name}: {e}", color="red")
        return False


def check_files(directory: Path):
    mismatched_files = []
    shebang_fixed = 0
    mime_fixed = 0

    print(f"\nScanning directory: {directory}")
    print("=" * 60)

    for root, _, files in os.walk(directory):
        if any(skip_dir in Path(root).parts for skip_dir in SKIP_DIRS):
            continue

        for name in files:
            path = Path(root) / name

            if any(skip_dir in path.parts for skip_dir in SKIP_DIRS):
                continue

            ext = path.suffix.lower()
            if ext in {".css", ".js", ".html", ".htm", ".xml", ".json"}:
                continue

            if fix_by_shebang(path):
                shebang_fixed += 1
                continue

            try:
                mime = get_file_mime(path)
                if not mime:
                    continue

                mime = mime.strip()
                expected_exts = MIME2EXT.get(mime, [])

                if not expected_exts:
                    continue

                if ".txt" in expected_exts and ext in {
                    ".txt",
                    ".text",
                    ".log",
                    ".md",
                    ".rst",
                }:
                    continue

                if ext and ext in expected_exts:
                    continue

                new_ext = expected_exts[0]

                if not ext and not new_ext:
                    continue

                new_name = path.stem + new_ext
                new_path = Path(root) / new_name

                if new_name == name:
                    continue

                if new_path.exists():
                    new_path = unique_path(new_path)

                if CONFIRM:
                    cprint(f"\n{path.name}", color="yellow", attrs=["bold"])
                    print(f"  Current extension: {ext or '(none)'}")
                    print(f"  Detected MIME type: {mime}")
                    print(f"  Expected extensions: {expected_exts}")
                    print(f"  Proposed new name: {new_path.name}")
                    ans = input(f"  Rename? (y/n): ").lower().strip()
                    if ans != "y":
                        continue

                path.rename(new_path)
                cprint(f"✓ Renamed: {path.name} -> {new_path.name}", color="green")
                mime_fixed += 1
                mismatched_files.append((path, ext, mime, new_path))

            except Exception as e:
                cprint(f"✗ Error processing {path.name}: {e}", color="red")

    print("\n" + "=" * 60)
    print("SUMMARY:")
    print(f"  Files fixed by shebang: {shebang_fixed}")
    print(f"  Files fixed by MIME type: {mime_fixed}")
    print(f"  Total files fixed: {shebang_fixed + mime_fixed}")

    if not shebang_fixed and not mime_fixed:
        cprint("  ✓ No extension mismatches found!", color="green")

    return mismatched_files


def main() -> None:
    cwd = Path.cwd()

    try:
        ret, _, _ = runcmd(["which", "file"], show_output=False)
        if ret != 0:
            cprint("Error: 'file' command not found. Please install it first.", color="red")
            cprint("  Ubuntu/Debian: sudo apt-get install file", color="yellow")
            cprint("  macOS: brew install file (usually pre-installed)", color="yellow")
            sys.exit(1)
    except Exception:
        pass

    print(f"\n{'=' * 60}")
    cprint("File Extension Mismatch Detector and Fixer", attrs=["bold"], color="cyan")
    print(f"{'=' * 60}")

    if CONFIRM:
        cprint("Running in CONFIRMATION mode (-y flag)", color="yellow")
        cprint("You will be prompted before each rename.", color="yellow")
    else:
        cprint("Running in AUTOMATIC mode", color="yellow")
        cprint("Use -y flag for confirmation mode.", color="yellow")

    mismatches = check_files(cwd)

    if mismatches:
        print(f"\n{'=' * 60}")
        print(f"Files with MIME-based mismatches: {len(mismatches)}")
        for path, ext, mime, new_path in mismatches:
            if new_path:
                cprint(
                    f"  {path.name} ({ext or 'no ext'}) -> {new_path.name} [{mime}]",
                    color="cyan",
                )
    else:
        cprint("\nNo extension mismatches found!", color="green")


if __name__ == "__main__":
    main()
