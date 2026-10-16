import sys
import json
import re
from pathlib import Path


def is_transliterated(persian_text: str) -> bool:

    text = persian_text.strip()

    if not text or len(text) < 2:
        return True

    persian_chars = set("ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")

    persian_count = sum(1 for c in text if c in persian_chars)

    if persian_count / len(text) < 0.6:
        return True

    transliteration_patterns = [
        r"^زیمو",
        r"^انزیم",
        r"^مخمر",
        r"^تخمیر",
    ]

    words = text.split()
    if len(words) == 1 and len(text) > 5:
        if re.search(r"(ولوژی|پلاستیک|سکوپ|ستنیک|تیک)$", text):
            return True

    english_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
    if any(c in english_chars for c in text):
        return True

    return False


def process_dictionary(filepath: Path):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            dictionary = json.load(f)
    except FileNotFoundError:
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in '{filepath}': {e}")
        sys.exit(1)

    removed_count = 0
    removed_entries = []

    for word, translations in list(dictionary.items()):
        if not isinstance(translations, list):
            continue

        original_count = len(translations)
        filtered_translations = [t for t in translations if not is_transliterated(t)]

        if len(filtered_translations) != original_count:
            removed = [t for t in translations if t not in filtered_translations]
            removed_entries.append((word, removed))
            removed_count += len(removed)

            if filtered_translations:
                dictionary[word] = filtered_translations
            else:
                del dictionary[word]

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(dictionary, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"Processing complete!")
    print(f"Total transliterated items removed: {removed_count}")
    print(f"{'=' * 60}\n")

    if removed_entries:
        print("Removed entries:")
        print("-" * 60)
        for word, removed in removed_entries:
            print(f"  '{word}':")
            for item in removed:
                print(f"    - {item}")
        print("-" * 60)
    else:
        print("No transliterated entries found.")


def main():
    if len(sys.argv) != 2:
        print("Usage: python script.py <dictionary.json>")
        sys.exit(1)

    filepath = Path(sys.argv[1])
    process_dictionary(filepath)


if __name__ == "__main__":
    main()
