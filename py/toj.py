import json
import sys
from pathlib import Path


def convert_delimited_to_json(filename: str) -> None:
    data = []
    field_names = [
        "id",
        "name",
        "url",
        "country",
        "languages",
        "is_subscription_required",
        "category",
        "description",
        "long_description",
    ]
    try:
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                fields = [field.strip() for field in line.split("||")]
                if len(fields) != len(field_names):
                    print(f"Skipping malformed line: {line.strip()}", file=sys.stderr)
                    continue
                record = {}
                for i, field_name in enumerate(field_names):
                    value = fields[i]
                    if field_name == "id":
                        try:
                            record[field_name] = int(value)
                        except ValueError:
                            print(
                                f"Warning: Could not convert ID '{value}' to int in line: {line.strip()}",
                                file=sys.stderr,
                            )
                            record[field_name] = value
                    elif field_name == "is_subscription_required":
                        record[field_name] = True if value.upper() == "YES" else False
                    elif field_name == "languages":
                        record[field_name] = [lang.strip() for lang in value.split(",")] if value else []
                    else:
                        record[field_name] = value
                data.append(record)
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
