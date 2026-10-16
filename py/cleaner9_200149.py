import sys
import re
import os


def clean_transcript(content):
    ansi_escape = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    content = ansi_escape.sub("", content)

    other_escape = re.compile(r"\x1b\][0-9;]*[^\x1b]*\x07")
    content = other_escape.sub("", content)

    content = content.replace("\r", "")

    while "\b" in content:
        content = re.sub(r".\b", "", content)
        content = content.replace("\b", "")

    content = content.replace("\x07", "")

    control_chars = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
    content = control_chars.sub("", content)

    lines = content.split("\n")
    cleaned_lines = [line.strip() for line in lines]
    content = "\n".join(cleaned_lines)

    content = re.sub(r"\n{3,}", "\n\n", content)

    return content


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <transcript_file>")
        sys.exit(1)

    filepath = sys.argv[1]

    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        cleaned_content = clean_transcript(content)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(cleaned_content)

        print(f"Successfully cleaned: {filepath}")

    except Exception as e:
        print(f"Error processing file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
