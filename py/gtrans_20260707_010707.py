
from googletrans import Translator
import sys
import re
import time


def translate_text(text, target_lang="en", retries=3):
    if not text or text.strip() == "":
        return text

    translator = Translator()
    attempt = 0

    while attempt < retries:
        try:
            detected = translator.detect(text)
            src_lang = detected.lang

            if src_lang == target_lang:
                return text

            translated = translator.translate(text, src_lang=src_lang, dest=target_lang)
            return translated.text

        except Exception as e:
            attempt += 1
            if attempt < retries:
                time.sleep(0.3 * attempt)
            else:
                print(f"Translation error after {retries} attempts: {e}", file=sys.stderr)
                return f"[Translation failed: {text[:50]}...]"

    return text


def is_tamil(text):
    tamil_pattern = re.compile(r"[\u0B80-\u0BFF]+")
    return bool(tamil_pattern.search(text))


def is_chinese(text):
    chinese_pattern = re.compile(r"[\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF]+")
    return bool(chinese_pattern.search(text))


def is_english(text):
    english_pattern = re.compile(r'^[A-Za-z0-9\s\.,;:!?\'"()\-—]+$')
    return bool(english_pattern.match(text.strip()))


def detect_language_type(line):
    if not line.strip():
        return "empty"
    if line.strip() == "%":
        return "marker"
    if is_tamil(line):
        return "tamil"
    if is_chinese(line):
        return "chinese"
    if is_english(line):
        return "english"
    return "other"


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

        lang_type = detect_language_type(line)

        if lang_type in ["empty", "marker"]:
            output_lines.append(line)
            continue

        if lang_type == "english":
            output_lines.append(line)
            continue

        if lang_type in ["tamil", "chinese", "other"]:
            print(f"Translating line {i + 1} ({lang_type})...", file=sys.stderr)
            translated = translate_text(line)
            output_lines.append(line)
            output_lines.append(f"→ {translated}")
            output_lines.append("")

    output_text = "\n".join(output_lines)

    if output_file:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(output_text)
            print(f"Output written to: {output_file}", file=sys.stderr)
        except Exception as e:
            print(f"Error writing output file: {e}", file=sys.stderr)
    else:
        print(output_text)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Translate Tamil/Chinese text in files to English (auto-detect mode).")
    parser.add_argument("input_file", help="Path to the input file to translate")
    parser.add_argument("-o", "--output", help="Path to output file (default: print to stdout)", default=None)
    args = parser.parse_args()
    process_file(args.input_file, args.output)


if __name__ == "__main__":
    main()
