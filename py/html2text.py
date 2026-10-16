import pathlib

INPUT = "input.html"
OUTPUT = "output.txt"


def strip_html_tags(input_file: str, output_file: str) -> None:
    inside_tag = False
    with (
        pathlib.Path(input_file).open(encoding="utf-8", errors="ignore") as f,
        pathlib.Path(output_file).open("w", encoding="utf-8") as out,
    ):
        for line in f:
            result = []
            for ch in line:
                if ch == "<":
                    inside_tag = True
                    continue
                if ch == ">":
                    inside_tag = False
                    continue
                if not inside_tag:
                    result.append(ch)
            cleaned = "".join(result).strip()
            if cleaned:
                out.write(cleaned + "\n")


strip_html_tags(INPUT, OUTPUT)
print("Stripped tags:", OUTPUT)
