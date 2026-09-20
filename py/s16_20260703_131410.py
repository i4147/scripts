CHUNKSIZE = 15850


def process_file(path):
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as infile:
            part_num = 0
            while True:
                chunk = infile.read(CHUNKSIZE)
                if not chunk:
                    break
                outpath = path.with_stem(path.stem + "_" + str(part_num))
                outpath.write_text(chunk, encoding="utf-8")

                print(f"Saved part {part_num} to '{output_path}'")
                part_num += 1
        print(f"File splitting complete. {part_num} parts created in '{output_dir}'.")
    except Exception as e:
        print(f"An error occurred during file splitting: {e}")


import sys
from pathlib import Path

from dh import get_files, mpf3


def main():
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []

    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_files(p))
    else:
        files = get_files(cwd)
    if len(files) == 1:
        process_file(files[0])
        sys.exit(1)

    mpf3(process_file, files)


if __name__ == "__main__":
    sys.exit(main())
