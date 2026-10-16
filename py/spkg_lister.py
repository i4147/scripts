import json
from operator import itemgetter
from pathlib import Path
from sys import exit

from dh import get_size


def main() -> None:
    outf = Path("/sdcard/spkgsorted")
    root = Path("/data/data/com.termux/files/usr/lib/python3.12/site-packages")
    dirs = [p for p in root.glob("*") if not p.is_file() and p.is_dir() and not "dist-info" in p.name]
    kp = {}
    with Path(outf).open("w", encoding="utf-8") as fo:
        for dr in dirs:
            path = Path(root / dr)
            psz = get_size(path)
            kp.setdefault(psz, []).append(path.name)
            fo.write(f"{psz} : {path.name}\n")
    kpsorted = sorted(kp.items(), key=itemgetter(1))
    j1 = Path("spkg.json")
    with Path(j1).open("w", encoding="utf-8") as f1:
        json.dump(kpsorted, f1, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    exit(main())
