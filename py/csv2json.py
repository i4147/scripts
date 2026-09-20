import sys
import json
from pathlib import Path


def csv_to_json(csv_file):
    json_file = csv_file.with_suffix(".json")
    data = []
    with open(csv_file, "r") as file:
        for line in file:
            parts = line.strip().split(",")
            if len(parts) >= 3:
                data.append(parts[:3])
    with json_file.open("w", encoding="utf8") as fo:
        json.dump(data, fo, ensure_ascii=False, indent=2, sort_keys=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <csv_file>")
        sys.exit(1)
    csv_file = Path(sys.argv[1])
    csv_to_json(csv_file)
