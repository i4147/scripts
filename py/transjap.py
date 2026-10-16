import re
import sys
from pathlib import Path

from deep_translator import GoogleTranslator

non_english_pattern = re.compile(r"[^\x00-\x7F]")


def is_english(text: str) -> bool:
    return not non_english_pattern.search(text)


def read_text_file(path: Path) -> str:
    allowed = {".txt", ".md", ".csv", ".json", ".py"}
    if path.suffix.lower() not in allowed:
        raise ValueError(msg)
    return path.read_text(encoding="utf-8")


def write_text_file(path: Path, data: str) -> None:
    path.write_text(data, encoding="utf-8")


def translate_text(text: str) -> str:
    if is_english(text):
        return text
    translator = GoogleTranslator(source="ja", target="en")
    return translator.translate(text)


def main() -> None:
    fn = Path(sys.argv[1])
    lines = read_lines(fn, ke=False)
    translated = []
    for line in lines:
        translated.append(translate_text(line))
    fn.write_text("\n".join(translated), encoding="utf8")
    print("done")


if __name__ == "__main__":
    main()
