import os
from pathlib import Path

dir = Path("/")
c = 0
lst = []
for path in dir.rglob("*"):
    if not os.access(path, os.R_OK):
        print(f"{path} no read access")
        prnt = str(path.parent)
        if prnt not in lst:
            lst.append(prnt)
        c += 1
print(f"total : {c}")
with Path("nonaccess").open("w", encoding="utf-8") as f:
    f.writelines(k + "\n" for k in lst)
