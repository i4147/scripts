import argparse
import os
import subprocess


def remove_unused_imports(directory) -> None:
    total_lines_removed = 0
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                try:
                    result = subprocess.run(
                        [
                            "autoflake",
                            "--remove-unused-imports",
                            "--in-place",
                            filepath,
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    lines_removed = 0
                    for line in result.stdout.splitlines():
                        if "Removed" in line:
                            try:
                                lines_removed = int(line.split(" ")[1])
                            except ValueError:
                                pass
                    total_lines_removed += lines_removed
                    if lines_removed > 0:
                        print(f"Removed {lines_removed} lines from {filepath}")
                    else:
                        print(f"No unused imports found in {filepath}")
                except subprocess.CalledProcessError as e:
                    print(f"Error processing {filepath}: {e}")
                except FileNotFoundError:
                    print("Error: autoflake not found.  Please install it (pip install autoflake)")
                    return
    print(f"\nTotal lines removed: {total_lines_removed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remove unused imports from Python files recursively.")
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="The directory to process (default: current directory)",
    )
    args = parser.parse_args()
    remove_unused_imports(args.directory)
