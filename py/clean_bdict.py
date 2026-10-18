def cbd(text):
    lines = text.splitlines()
    mixed_lower = {line.lower() for line in lines if any(c.isupper() for c in line)}
    cleaned_lines = [line for line in lines if not (line.islower() and line in mixed_lower)]
    result = {}
    for line in cleaned_lines:
        if ":" in line:
            key, value = line.split(":", 1)
            result[key] = value
    return result


with open("mapping") as f:
    text = f.read()
result = cbd(text)
import json

with open("const", "w") as fo:
    json.dump(result, fo, indent=2, ensure_ascii=False)
