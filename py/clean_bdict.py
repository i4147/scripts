def cbd(text):
    lines = text.splitlines()
    # Lowercased versions of lines that contain at least one uppercase character
    mixed_lower = {line.lower() for line in lines if any(c.isupper() for c in line)}
    # Keep lines that are not purely lowercase duplicates of a mixed-case line
    cleaned_lines = [line for line in lines if not (line.islower() and line in mixed_lower)]
    # Build dictionary from "key:value" lines
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
