from pathlib import Path
import re
import sys


def recover_text_part(input_file):
    src = Path(input_file)

    text = src.read_text(encoding="utf-8", errors="replace")

    html_markers = [
        "<!doctype html",
        "<html",
        "<HTML",
        "<head",
        "<body",
        "<BODY",
    ]

    positions = [text.find(marker) for marker in html_markers if text.find(marker) >= 0]

    if not positions:
        raise RuntimeError("Could not locate the HTML/text section.")

    html_start = min(positions)

    boundary_matches = list(re.finditer(r"(?m)^--[^\r\n]+", text[html_start:]))

    html_end = len(text)

    if boundary_matches:
        html_end = html_start + boundary_matches[0].start()

    recovered = text[html_start:html_end].strip()

    if re.search(r"<html\b|<!doctype\s+html", recovered, re.I):
        extension = ".html"
    else:
        extension = ".txt"

    output = src.with_name(src.stem + "_recovered" + extension)
    output.write_text(recovered + "\n", encoding="utf-8")

    print(f"Recovered {len(recovered):,} characters")
    print(f"Saved to: {output}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} damaged_file.mhtml")
        sys.exit(1)

    recover_text_part(sys.argv[1])
