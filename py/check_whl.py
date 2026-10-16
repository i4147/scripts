import shutil
from pathlib import Path

if __name__ == "__main__":
    cwd = Path.cwd()
    for path in cwd.glob("*.whl"):
        if not path.stat().st_size:
            continue
        indx = path.stem.index("-")
        pkgname = path.stem[:indx]
        print(f"{path.name}: {pkgname}")
        if Path(pkgname).exists():
            print(f"{pkgname} removed.")
            shutil.rmtree(pkgname)
