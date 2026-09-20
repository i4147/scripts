from pathlib import Path
from sys import exit

from dh import get_size
from termcolor import cprint


def main() -> None:
    root = Path.cwd()
    kp = {}
    files = [p for p in root.rglob("*") if p.is_file() and p.exists()]
    for f in files:
        path = Path(root / f)
        psz = get_size(path)
        kp.setdefault(psz, []).append(path.name)
    orig = kp
    kz = sorted(kp.keys())
    pk = {}
    for x in kz:
        pk[x] = orig.get(x)
    for k, v in pk.items():
        if len(v) > 1:
            cprint(f"{k}:", "cyan")
            for i in v:
                print(f"    - {i}")


if __name__ == "__main__":
    exit(main())
