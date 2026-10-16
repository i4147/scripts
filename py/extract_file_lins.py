import pathlib
import sys


def main() -> None:
    csslinks = []
    jslinks = []
    targz = []
    ziplinks = []
    tarxz = []
    with pathlib.Path("urls.txt").open(encoding="utf-8") as f:
        lines = f.readlines()
        for line in lines:
            if line.strip().endswith(".js"):
                jslinks.append(line)
            if line.strip().endswith("."):
                csslinks.append(line)
            if line.strip().endswith(".tar.gz"):
                targz.append(line)
            if line.strip().endswith(".tar.xz"):
                tarxz.append(line)
            if line.strip().endswith(".zip"):
                ziplinks.append(line)
    with pathlib.Path("jslinks.txt").open("w", encoding="utf-8") as fo:
        fo.writelines(jslinks)
    with pathlib.Path("csslinks.txt").open("w", encoding="utf-8") as fo:
        fo.writelines(csslinks)
    with pathlib.Path("ziplinks.txt").open("w", encoding="utf-8") as fo:
        fo.writelines(ziplinks)
    with pathlib.Path("targz.txt").open("w", encoding="utf-8") as fo:
        fo.writelines(targz)
    with pathlib.Path("tarxz.txt").open("w", encoding="utf-8") as fo:
        fo.writelines(tarxz)
    print("done")


if __name__ == "__main__":
    sys.exit(main())
