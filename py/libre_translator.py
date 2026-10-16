import requests
import sys
import re
import time


def translate_text(text, target_lang="en", retries=3):
    if not text or text.strip() == "":
        return text

    attempt = 0

    while attempt < retries:
        try:
            response = requests.post(
                "http://localhost:5000/translate", json={"q": text, "source": "auto", "target": target_lang}
            )

            if response.status_code == 200:
                return response.json()["translatedText"]

        except Exception as e:
            attempt += 1
            if attempt < retries:
                time.sleep(0.3 * attempt)
            else:
                print(f"Translation error: {e}", file=sys.stderr)
                return f"[Translation failed: {text[:50]}...]"

    return text


def is_tamil(text):
    return bool(re.search(r"[\u0B80-\u0BFF]+", text))


def is_chinese(text):
    return bool(re.search(r"[\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF]+", text))


def is_english(text):
    return bool(re.match(r'^[A-Za-z0-9\s\.,;:!?\'"()\-—]+$', text.strip()))


def process_file(input_file, output_file=None):
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: File '{input_file}' not found.", file=sys.stderr)
        return
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        return

    output_lines = []

    for i, line in enumerate(lines):
        line = line.rstrip("\n")

        if not line.strip() or line.strip() == "%":
            output_lines.append(line)
            continue

        if is_english(line):
            output_lines.append(line)
            continue

        print(f"Translating line {i + 1}...", file=sys.stderr)
        translated = translate_text(line)
        output_lines.append(line)
        output_lines.append(f"→ {translated}")
        output_lines.append("")

    output_text = "\n".join(output_lines)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"Output written to: {output_file}", file=sys.stderr)
    else:
        print(output_text)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Translate files using LibreTranslate")
    parser.add_argument("input_file", help="Path to the input file")
    parser.add_argument("-o", "--output", help="Output file path", default=None)
    args = parser.parse_args()
    process_file(args.input_file, args.output)


if __name__ == "__main__":
    main()
