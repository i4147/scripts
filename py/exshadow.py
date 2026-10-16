#!/usr/bin/env python3
import json
import sys


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <json_file>", file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    conflicts = data.get("conflicts", [])

    shadows = [c["shadows"] for c in conflicts if isinstance(c, dict) and c.get("shadows")]

    with open("req.txt", "w", encoding="utf-8") as out:
        out.write("\n".join(shadows))
        if shadows:
            out.write("\n")

    print(f"Extracted {len(shadows)} shadows -> req.txt")


if __name__ == "__main__":
    main()
