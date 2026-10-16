import pathlib

nl = []
with pathlib.Path("/sdcard/emoji").open(encoding="utf-8") as f:
    data = f.read()
    chars = data.strip().split()
    for c in chars:
        charlist.append(c)
with pathlib.Path("/sdcard/emoji").open("w", encoding="utf-8") as fo:
    fo.writelines(nl)
