from googletrans import Translator
import sys
import re
import time


def translate_text(text, target_lang="en"):
    if not text or text.strip() == "":
        return text
    try:
        translator = Translator()
        translated = translator.translate(text, dest=target_lang)
        return translated.text
    except Exception as e:
        print(f"Translation error: {e}", file=sys.stderr)
        return f"[Translation failed: {text}]"


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
    english_pattern = re.compile("^[A-Za-z0-9\\s\\.,;:!?\\'\"()-]+$")
    for i, line in enumerate(lines):
        line = line.rstrip("\n")
        original_line = line
        if not line.strip():
            output_lines.append(line)
            continue
        is_english = english_pattern.match(line.strip())
        if line.strip() == "%":
            output_lines.append(line)
            continue
        if not is_english:
            print(f"Translating line {i + 1}...", file=sys.stderr)
            translated = translate_text(line)
            output_lines.append(f"{line}")
            output_lines.append(f"→ {translated}")
            output_lines.append("")
            time.sleep(0.5)
        else:
            output_lines.append(line)
    if output_file:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("\n".join(output_lines))
            print(f"Output written to: {output_file}")
        except Exception as e:
            print(f"Error writing output file: {e}", file=sys.stderr)
    else:
        print("\n".join(output_lines))


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Translate Tamil text in files to English while preserving English content."
    )
    parser.add_argument("input_file", help="Path to the input file to translate")
    parser.add_argument("-o", "--output", help="Path to output file (default: print to stdout)", default=None)
    args = parser.parse_args()
    process_file(args.input_file, args.output)


if __name__ == "__main__":
    main()
