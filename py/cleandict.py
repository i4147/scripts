import json
import os

INPUT = "merged.json"
REMOVED = "removed.json"

# Load
with open(INPUT, "r", encoding="utf-8") as f:
    data = json.load(f)


def should_remove(key, values):
    stripped_key = key.strip()
    # Remove if key starts with a number
    if stripped_key and stripped_key[0].isdigit():
        return True
    # Remove if key is a single letter (ignoring surrounding whitespace)
    if len(stripped_key) == 1:
        return True
    # Remove if values has exactly one item and that item is a single letter
    if len(values) == 1 and len(values[0].strip()) == 1:
        return True
    return False


# Split into kept and removed
cleaned = {}
removed = {}
for k, v in data.items():
    if should_remove(k, v):
        removed[k] = v
    else:
        cleaned[k] = v

print(f"Removed {len(removed)} records. {len(cleaned)} remaining.")

# Write removed records to removed.json
with open(REMOVED, "w", encoding="utf-8") as f:
    json.dump(removed, f, ensure_ascii=False, indent=2)

# Write cleaned data back to merged.json in place
tmp = INPUT + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(cleaned, f, ensure_ascii=False, indent=2)
os.replace(tmp, INPUT)

print(f"Done. Check '{REMOVED}' to review removed records.")
