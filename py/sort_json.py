import json
import operator
import pathlib
import sys


def sort_json_by_second_item(input_file: str) -> None:
    with pathlib.Path(input_file).open(encoding="utf-8") as file:
        data = json.load(file)
    sorted_data = dict(sorted(data.items(), key=operator.itemgetter(1)))
    with pathlib.Path("sorted.json").open("w", encoding="utf-8") as sorted_file:
        json.dump(sorted_data, sorted_file, indent=4)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <filename>")
        sys.exit(1)
    input_filename = sys.argv[1]
    sort_json_by_second_item(input_filename)
