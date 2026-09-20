import pathlib
import sys


def reformat_srt(filename: str) -> None:
    with pathlib.Path(filename).open(encoding="utf-8") as f:
        lines = f.readlines()
    blocks = []
    current = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        current.append(line)
        if "-->" in line:
            blocks.append(current)
            current = []
    formatted_blocks = []
    counter = 1
    for block in blocks:
        ts_line = block[0]
        text_lines = block[1:]
        formatted_blocks.append(f"{counter}\n{ts_line}\n" + "\n".join(text_lines))
        counter += 1
    formatted_content = "\n\n".join(formatted_blocks) + "\n"
    pathlib.Path(filename).write_text(formatted_content, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fix_srt.py 02.srt")
        sys.exit(1)
    reformat_srt(sys.argv[1])
    print(f"Reformatted {sys.argv[1]} successfully.")
