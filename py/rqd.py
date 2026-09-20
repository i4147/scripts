import pathlib

nl = []
with pathlib.Path("rqdist.txt").open(encoding="utf-8") as f:
    lines = f.readlines()
    nl.extend(line for line in lines if not "extra ==" in line)
with pathlib.Path("rqdist.txt").open("w", encoding="utf-8") as fo:
    fo.writelines(nl)
