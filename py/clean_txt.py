import os

lst = []
cleaned = []
with open("txt.txt") as f:
    for line in f:
        lst.append(line.strip())
for f in os.listdir("."):
    parts = f.split("-")
    if not parts[0] in lst:
        print(parts[0])
        cleaned.append(parts[0])
with open("txt2.txt", "w") as fo:
    fo.write("\n".join(cleaned))
