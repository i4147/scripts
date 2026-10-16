import json
import os
from collections import defaultdict


def find_mime_json_files(root_dir):
    json_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith(".json"):
                json_files.append(os.path.join(dirpath, filename))
    return json_files


def parse_mime_info(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None
    if "@type" not in data:
        return None
    mime_type = data["@type"]
    extensions = []
    glob_data = data.get("glob", [])
    if isinstance(glob_data, list):
        for glob_item in glob_data:
            if "@pattern" in glob_item:
                pattern = glob_item["@pattern"]
                if pattern.startswith("*"):
                    ext = pattern[1:]
                    extensions.append(ext)
    elif isinstance(glob_data, dict):
        if "@pattern" in glob_data:
            pattern = glob_data["@pattern"]
            if pattern.startswith("*"):
                ext = pattern[1:]
                extensions.append(ext)
    if mime_type and extensions:
        return mime_type, extensions
    return None


def build_mime_to_ext_dict(root_dir: str):
    mime_to_ext = defaultdict(list)
    json_files = find_mime_json_files(root_dir)
    for file_path in json_files:
        result = parse_mime_info(file_path)
        if result:
            mime_type, exts = result
            for ext in exts:
                if ext not in mime_to_ext[mime_type]:
                    mime_to_ext[mime_type].append(ext)
    return dict(mime_to_ext)


def main() -> None:
    current_dir = "."
    output_file = "mime_to_ext.json"
    print(f"Scanning directory: {current_dir}")
    mime_dict = build_mime_to_ext_dict(current_dir)
    if not mime_dict:
        print("No MIME info JSON files found or parsed.")
        return
    sorted_mime_dict = dict(sorted(mime_dict.items()))
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(sorted_mime_dict, f, indent=4, ensure_ascii=False)
    print(f"Successfully saved {len(sorted_mime_dict)} MIME types to {output_file}")
    print("\nExamples:")
    for i, (mime, exts) in enumerate(sorted_mime_dict.items()):
        if i >= 5:
            break
        print(f"  {mime}: {exts}")


if __name__ == "__main__":
    main()
