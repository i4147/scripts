import sys
import urllib


def reporthook(*a) -> None:
    print(a)


def main() -> None:
    for url in sys.argv[1:]:
        indx = url.rfind("/")
        file = url[indx + 1 :]
        print(f"{url} -> {file}")
        urllib.urlretrieve(url, file, reporthook)


if __name__ == "__main__":
    main()
