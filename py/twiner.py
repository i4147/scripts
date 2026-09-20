import sys
from pathlib import Path
from time import perf_counter

import fastwalk


def main() -> None:
    start = perf_counter()
    for pth in fastwalk.walk_files("."):
        path = Path(pth)
        if path.is_file() and path.suffix == ".ttf":
            twin = Path(str(path.parent) + "/" + path.stem + ".woff2")
            if twin.exists() and twin != path:
                print(path)
                print(twin)
                twin.unlink()
    print(f"{perf_counter() - start} sec")


if __name__ == "__main__":
    sys.exit(main())
