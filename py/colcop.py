import os
import pathlib

nl = []
for f in os.listdir("."):
    if f.endswith(".map"):
        with pathlib.Path(f).open(encoding="utf-8") as f:
            for line in f:
                if "copyright" in line.lower():
                    if not line in nl:
                        nl.append(line)
                    else:
                        print("dup line")
with pathlib.Path("lic").open("w", encoding="utf-8") as fo:
    fo.writelines(nl)
