
import json
import sys


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <input.json>", file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: file not found: {input_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {input_file}: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, dict):
        print("Error: JSON root is not an object ({key: value, ...})", file=sys.stderr)
        sys.exit(1)

    with open("keys.txt", "w", encoding="utf-8") as f:
        for key in data.keys():
            f.write(f"{key}\n")

    print(f"Wrote {len(data)} keys to keys.txt")


if __name__ == "__main__":
    main()
