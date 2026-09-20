import hashlib
from pathlib import Path


def get_hash(p):
    try:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for c in iter(lambda: f.read(8192), b""):
                h.update(c)
        return h.hexdigest()
    except:
        return None



system = {}
for f in Path("/system/bin").iterdir():
    if f.is_file() or f.is_symlink():
        h = get_hash(f)
        if h:
            system[h] = f.name


matches = []
for f in Path(".").iterdir():
    if f.is_file():
        h = get_hash(f)
        if h and h in system:
            matches.append((f.name, system[h]))


if matches:
    print(f"⚠️  Found {len(matches)} matches:")
    print("\n".join(f"  {a} -> /system/bin/{b}" for a, b in matches))
else:
    print("✅ No matches found")
print(f"📊 Checked {len(system)} system files")
