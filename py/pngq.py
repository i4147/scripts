import subprocess
from pathlib import Path

QUALITY_RANGE = "70-80"
COMPRESSION_SPEED = 4
START_PATH = Path.cwd()
PNGQUANT_COMMAND = "pngquant"


def get_file_size_human(filepath: Path) -> str:
    try:
        result = subprocess.run(
            ["du", "-h", str(filepath)],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.split()[0]
    except subprocess.CalledProcessError:
        return "ERROR"
    except FileNotFoundError:
        return "N/A (du command not found)"


def optimize_png(file_path: Path) -> None:
    original_size = get_file_size_human(file_path)
    print(f"Processing: {file_path.relative_to(START_PATH)} (Original Size: {original_size})")
    try:
        command = [
            PNGQUANT_COMMAND,
            f"--quality={QUALITY_RANGE}",
            f"--speed={COMPRESSION_SPEED}",
            "--strip",
            "--skip-if-larger",
            "--ext",
            ".",
            "--force",
            str(file_path),
        ]
        subprocess.run(
            command,
            check=True,
            capture_output=True,
        )
        new_size = get_file_size_human(file_path)
        if original_size != new_size:
            print(f"   -> SUCCESS: New Size: {new_size}")
        else:
            print("   -> SKIPPED: File size did not change (either already optimized or below quality threshold).")
    except subprocess.CalledProcessError as e:
        print(f"   -> **ERROR**: Optimization failed for {file_path}. Details: {e.stderr.strip()}")
    except FileNotFoundError:
        print(
            f"   -> **CRITICAL ERROR**: The '{PNGQUANT_COMMAND}' command was not found. Please ensure it is installed and in your system's PATH."
        )
        raise
    except Exception as e:
        print(f"   -> **UNEXPECTED ERROR**: {e}")
    newpath = file_path
    oldpath = str(file_path).replace("png", "")
    Path(file_path).unlink()
    Path(oldpath).rename(newpath)


def main() -> None:
    print("Starting recursive PNG optimization using pngquant...")
    print(f"Quality Range: {QUALITY_RANGE} | Compression Speed: {COMPRESSION_SPEED}")
    print("-" * 70)
    png_files_found = 0
    for file_path in START_PATH.rglob("*.png"):
        if file_path.is_file():
            optimize_png(file_path)
            png_files_found += 1
    print("-" * 70)
    print("Optimization complete.")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError:
        print("\nScript terminated because a required external command was missing.")
