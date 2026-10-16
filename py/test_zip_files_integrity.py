import os
import sys
import zipfile

from termcolor import cprint


def check_integrity(file: str) -> None:
    try:
        with zipfile.ZipFile(file, "r") as zf:
            bad_file = zf.testzip()
            if bad_file is not None:
                cprint(
                    f"{file} has error in {bad_file}",
                    "cyan",
                )
            else:
                cprint(f"{file} is OK", "green")
    except zipfile.BadZipFile:
        print(f"{file} is not a valid zip file")


def main() -> None:
    files = [f for f in os.listdir(".") if f.endswith(".zip")]
    if not files:
        print("No zip files found in current directory")
        sys.exit(0)
    for f in files:
        check_integrity(f)


if __name__ == "__main__":
    main()
