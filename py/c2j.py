import json
import sys
from pathlib import Path


def convert_delimited_to_json(filename: str) -> None:
    data = []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                if "\t" in line:
                    lcode, lang = line.split("\t")
                    data.append({"lang_code": lcode, "lang": lang})
        jsonfile = Path(filename).with_suffix(".json")
        with jsonfile.open("w", encoding="utf-8") as fo:
            json.dump(data, fo, indent=2, ensure_ascii=False)
    except FileNotFoundError:
        print(f"Error: File not found at {filename}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script_name.py <filename>", file=sys.stderr)
        sys.exit(1)
    input_filename = sys.argv[1]
    convert_delimited_to_json(input_filename)
