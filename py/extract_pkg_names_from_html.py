import pathlib

INPUT = "/sdcard/Download/python.html"
OUTPUT = "pip.txt"


def extract_packages(input_file: str, output_file: str) -> None:
    with (
        pathlib.Path(input_file).open(encoding="utf-8", errors="ignore") as f,
        pathlib.Path(output_file).open("w", encoding="utf-8") as out,
    ):
        write = out.write
        for line in f:
            line = line.strip()
            if "<a " not in line:
                continue
            start = line.find(">")
            if start == -1:
                continue
            end = line.find("<", start + 1)
            if end == -1:
                continue
            pkg = line[start + 1 : end].strip()
            if pkg:
                print(pkg, end=" ")
                write(pkg + "\n")


extract_packages(INPUT, OUTPUT)
print("Completed.")
