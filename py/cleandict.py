import json
import os

INPUT = "merged.json"
REMOVED = "removed.json"
with open(INPUT, "r", encoding="utf-8") as f:
    data = json.load(f)


def should_remove(key, values):
    stripped_key = key.strip()
    if stripped_key and stripped_key[0].isdigit():
        return True
    if len(stripped_key) == 1:
        return True
    if len(values) == 1 and len(values[0].strip()) == 1:
        return True
    return False


cleaned = {}
removed = {}
for k, v in data.items():
    if should_remove(k, v):
        removed[k] = v
    else:
        cleaned[k] = v
print(f"Removed {len(removed)} records. {len(cleaned)} remaining.")
with open(REMOVED, "w", encoding="utf-8") as f:
    json.dump(removed, f, ensure_ascii=False, indent=2)
tmp = INPUT + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(cleaned, f, ensure_ascii=False, indent=2)
os.replace(tmp, INPUT)
print(f"Done. Check '{REMOVED}' to review removed records.")
