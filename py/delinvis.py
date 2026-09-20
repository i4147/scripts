import pathlib
import shutil
import string
import sys


def remove_unprintable_chars(input_file: str) -> None:
    backup_file = input_file + ".bak"
    pathlib.Path(input_file).replace(backup_file)
    with (
        pathlib.Path(backup_file).open("rb") as f_in,
        pathlib.Path(input_file).open("wb") as f_out,
    ):
        for line in f_in:
            decoded_line = line.decode("latin-1")
            filtered_line = "".join(char for char in decoded_line if char in {"\n", "\r", "\t"} or char.isprintable())
            f_out.write(filtered_line.encode("utf-8"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <input_file>")
        sys.exit(1)
    input_file = sys.argv[1]
    if not pathlib.Path(input_file).exists():
        print(f"Error: File '{input_file}' not found.")
        sys.exit(1)
    remove_unprintable_chars(input_file)
    print(f"File '{input_file}' cleaned. Backup created as '{input_file}.bak'")


def find_unprintable_positions(text: str):
    allowed = set(string.printable) | {
        "\n",
        "\r",
        "\t",
    }
    positions = []
    line_num = 1
    col_num = 1
    for ch in text:
        if ch not in allowed:
            positions.append((line_num, col_num, ch, ord(ch)))
        if ch == "\n":
            line_num += 1
            col_num = 1
        else:
            col_num += 1
    return positions


def clean_text(text: str) -> str:
    allowed = set(string.printable) | {
        "\n",
        "\r",
        "\t",
    }
    return "".join(ch for ch in text if ch in allowed)


def clean_file(path: str) -> None:
    backup_path = path + ".bak"
    shutil.copy2(path, backup_path)
    data = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    positions = find_unprintable_positions(data)
    if positions:
        print(f"Found {len(positions)} unprintable character(s):")
        for line, col, _ch, code in positions:
            print(f"  Line {line}, Col {col}: char code {code} (0x{code:02X})")
    else:
        print("No unprintable characters found.")
    cleaned = clean_text(data)
    pathlib.Path(path).write_text(cleaned, encoding="utf-8", errors="ignore")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {pathlib.Path(sys.argv[0]).name} <filename>")
        sys.exit(1)
    fname = sys.argv[1]
    if not pathlib.Path(fname).is_file():
        print(f"Error: '{fname}' is not a file")
        sys.exit(1)
    clean_file(fname)


if __name__ == "__main__":
    main()
