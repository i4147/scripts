import pathlib

lines = []
with pathlib.Path(".dircolors").open(encoding="utf-8") as f:
    lines = f.readlines()
for line in lines:
    if not line.startswith("."):
        s = line.strip().split(" ")
        new_line = s[0][:2].lower() + "=" + s[1] + ":\n"
        nl.append(new_line)
    else:
        s = line.strip().split(" ")
        new_line = s[0] + "=" + s[1] + ":\n"
        nl.append(new_line)
with pathlib.Path("dc2").open("w", encoding="utf-8") as fo:
    fo.writelines(nl)
print("done")
