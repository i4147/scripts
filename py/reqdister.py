from sys import exit
from time import perf_counter

from dh import get_installed_pkgs


def process_file(fp: str) -> None:
    nl = []
    pkgs = get_installed_pkgs()
    with open(fp) as f:
        lines = f.readlines()
        for line in lines:
            cleaned = line.strip().lower()
            if cleaned not in pkgs:
                nl.append(cleaned)
            """
            idx=len(cleaned)
            if "<"in line:
                idx=cleaned.find("<")
            elif ">" in line:
                idx=cleaned.find(">")
            elif "=" in line:
                idx=cleaned.find("=")
            if idx:
                cleaned=cleaned[:idx]
            """
            """
            if "requires-dist" in line.lower():
                cleaned=cleaned.replace("requires-dist: ","")
                cleaned=cleaned.replace('extra="doc"',"")
            """
    with open(fp, "w") as fo:
        for k in nl:
            fo.write(k + "\n")


def main() -> None:
    start = perf_counter()
    process_file("reqdist.txt")
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
