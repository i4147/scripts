
import os
import sys
import subprocess
from pathlib import Path
from binaryornot import is_binary


def get_path_dirs() -> list[str]:
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    current_dir = os.getcwd()
    if current_dir not in path_dirs:
        path_dirs.append(current_dir)
    return path_dirs


def is_executable(filepath) -> bool:
    return os.path.isfile(filepath) and os.access(filepath, os.X_OK)


def get_binary_files(directory):
    binaries = []
    try:
        for item in os.listdir(directory):
            filepath = os.path.join(directory, item)
            if is_executable(filepath):
                try:
                    with open(filepath, "rb") as f:
                        header = f.read(4)
                        if header[:4] == b"\x7fELF":
                            binaries.append(filepath)
                        elif header[:2] == b"#!":
                            binaries.append(filepath)
                except (IOError, OSError):
                    continue
    except PermissionError:
        pass
    return binaries


def test_executable(filepath):
    try:
        for test_arg in ["--help", "-h", "--version", "-v"]:
            try:
                result = subprocess.run([filepath, test_arg], capture_output=True, text=True, timeout=1)
                if result.returncode == 0:
                    return (True, None)
            except (subprocess.TimeoutExpired, subprocess.SubprocessError):
                continue
        result = subprocess.run([filepath], capture_output=True, text=True, timeout=1)
        if result.stderr:
            if any(
                (
                    pattern in result.stderr.lower()
                    for pattern in [
                        "error while loading shared libraries",
                        "cannot open shared object file",
                        "no such file",
                        "not found",
                    ]
                )
            ):
                return (False, result.stderr.strip())
        return (True, None)
    except FileNotFoundError as e:
        return (False, f"File not found: {e}")
    except subprocess.TimeoutExpired:
        return (True, None)
    except PermissionError:
        return (False, "Permission denied")
    except OSError as e:
        if "exec format error" in str(e):
            return (False, "Exec format error (possibly wrong architecture)")
        return (False, str(e))


def main() -> None:
    output_dir = Path.home() / "tmp"
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "err"
    path_dirs = get_path_dirs()
    seen = set()
    unique_dirs = []
    for d in path_dirs:
        if d not in seen and os.path.exists(d):
            seen.add(d)
            unique_dirs.append(d)
    failed_binaries = []
    print(f"Scanning {len(unique_dirs)} directories...")
    for directory in unique_dirs:
        print(f"  Checking: {directory}")
        binaries = get_binary_files(directory)
        for binary in binaries:
            if not is_binary(binary):
                continue
            print(f"    Testing: {os.path.basename(binary)}")
            success, error_msg = test_executable(binary)
            if not success:
                failed_binaries.append({"path": binary, "error": error_msg or "Unknown error"})
    with open(output_file, "w") as f:
        if failed_binaries:
            f.write(f"Found {len(failed_binaries)} problematic binaries:\n")
            f.write("=" * 60 + "\n\n")
            for fb in failed_binaries:
                f.write(f"Binary: {fb['path']}\n")
                f.write(f"Error:  {fb['error']}\n")
                f.write("-" * 60 + "\n")
        else:
            f.write("No problematic binaries found.\n")
    print("\n" + "=" * 60)
    if failed_binaries:
        print(f"❌ Found {len(failed_binaries)} problematic binaries")
        print(f"Details written to: {output_file}")
        print("\nFirst few errors:")
        for fb in failed_binaries[:5]:
            print(f"  {fb['path']}")
            print(f"    → {fb['error'][:100]}")
    else:
        print("✅ No problematic binaries found")
        print(f"Report written to: {output_file}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nScan interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)
