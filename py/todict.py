from dh import PKG_MAPPING

with open("mapping") as f:
    text = f.read()
pairs = [tuple(line.split(":", 1)) for line in text.strip().splitlines() if line.strip()]
b = PKG_MAPPING
with open("c", "w") as fo:
    for k, v in b.items():
        fo.write(f"{k}:{v}\n")
print("done")
